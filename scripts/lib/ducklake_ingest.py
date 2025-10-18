"""Shared DuckLake ingestion helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = PROJECT_ROOT / "catalog.db"


class IngestError(RuntimeError):
    """Raised when ingestion fails."""


@dataclass(slots=True)
class EnvConfig:
    """Resolved configuration derived from environment variables."""

    access_key: str
    secret_key: str
    bucket: str
    endpoint_host: str
    endpoint_url: str
    use_ssl: bool
    metadata_path: Path
    data_path: str


def project_root() -> Path:
    """Return the repository root."""
    return PROJECT_ROOT


def catalog_path() -> Path:
    """Return the DuckDB catalog location."""
    return CATALOG_PATH


def _load_dotenv() -> dict[str, str]:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values.setdefault(key.strip(), value.strip())
    return values


DOTENV_CACHE = _load_dotenv()


def get_env_value(key: str, *, default: str | None = None, required: bool = False) -> str:
    """Fetch an environment variable, falling back to `.env` values when present."""
    if key in os.environ:
        value = os.environ[key].strip()
        if value:
            return value

    if key in DOTENV_CACHE:
        value = DOTENV_CACHE[key].strip()
        if value:
            return value

    if default is not None:
        return default
    if required:
        raise IngestError(f"Environment variable '{key}' is required but not set.")
    raise IngestError(f"Environment variable '{key}' is missing and no default provided.")


def resolve_path(value: str) -> Path:
    """Resolve a file-system path relative to the project root."""
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def resolve_storage_path(value: str) -> str:
    """Resolve storage locations, supporting both local and S3-style paths."""
    if value.startswith(("s3://", "http://", "https://")):
        return value.rstrip("/")
    raise IngestError(
        "DUCKLAKE_DATA_PATH must be an object-store URI such as 's3://bucket/ducklake'. "
        f"Received '{value}'."
    )


def escape_sql_literal(value: str) -> str:
    """Escape a string literal for embedding in DuckDB SQL."""
    return value.replace("'", "''")


def normalize_endpoint(value: str) -> tuple[str, bool]:
    """Convert a user-provided endpoint into host:port and SSL flag."""
    if "://" in value:
        parsed = urlparse(value)
        host = parsed.netloc or parsed.path
        use_ssl = parsed.scheme.lower() == "https"
    else:
        host = value
        use_ssl = False
    if not host:
        raise IngestError(f"Invalid MINIO_ENDPOINT value: '{value}'")
    return host.strip("/"), use_ssl


def build_env_config() -> EnvConfig:
    """Gather required connection values from environment and defaults."""
    access_key = get_env_value("MINIO_ROOT_USER", required=True)
    secret_key = get_env_value("MINIO_ROOT_PASSWORD", required=True)
    bucket = get_env_value("MINIO_BUCKET_NAME", required=True)
    endpoint_raw = get_env_value("MINIO_ENDPOINT", default="http://127.0.0.1:9000").rstrip("/")
    endpoint_host, use_ssl = normalize_endpoint(endpoint_raw)
    metadata = resolve_path(get_env_value("DUCKLAKE_METADATA_PATH", default="ducklake/catalog.duckdb"))
    default_data_path = f"s3://{bucket}/ducklake"
    data_path = resolve_storage_path(get_env_value("DUCKLAKE_DATA_PATH", default=default_data_path))
    return EnvConfig(
        access_key=access_key,
        secret_key=secret_key,
        bucket=bucket,
        endpoint_host=endpoint_host,
        endpoint_url=endpoint_raw,
        use_ssl=use_ssl,
        metadata_path=metadata,
        data_path=data_path,
    )


def ensure_duckdb_binary(explicit_path: str | None = None) -> str:
    """Locate the DuckDB CLI executable."""
    candidate = explicit_path or get_env_value("DUCKDB", default="duckdb")
    duckdb_binary = shutil.which(candidate)
    if duckdb_binary is None:
        raise IngestError(
            f"duckdb CLI not found (looked for '{candidate}'). "
            "Install DuckDB or set DUCKDB environment variable."
        )
    return duckdb_binary


def build_s3_statements(env_config: EnvConfig) -> list[str]:
    """Return SET statements configuring DuckDB's S3 connector for MinIO."""
    endpoint = escape_sql_literal(env_config.endpoint_host)
    access_key = escape_sql_literal(env_config.access_key)
    secret_key = escape_sql_literal(env_config.secret_key)
    ssl_flag = "true" if env_config.use_ssl else "false"
    return [
        f"SET s3_endpoint='{endpoint}'",
        "SET s3_url_style='path'",
        f"SET s3_use_ssl={ssl_flag}",
        f"SET s3_access_key_id='{access_key}'",
        f"SET s3_secret_access_key='{secret_key}'",
    ]


def ducklake_attach_statement(env_config: EnvConfig) -> str:
    """Return the ATTACH statement needed for DuckLake."""
    metadata = escape_sql_literal(env_config.metadata_path.as_posix())
    data_path = escape_sql_literal(env_config.data_path)
    return (
        f"ATTACH '{metadata}' AS ducklake "
        f"(TYPE DUCKLAKE, DATA_PATH '{data_path}', OVERRIDE_DATA_PATH true)"
    )


def run_duckdb(statements: Iterable[str], *, duckdb_binary: str) -> subprocess.CompletedProcess[str]:
    """Execute a sequence of SQL statements against catalog.db."""
    cleaned = [stmt.strip().rstrip(";") for stmt in statements if stmt and stmt.strip()]
    statement = ";\n".join(cleaned) + ";"
    result = subprocess.run(
        [duckdb_binary, str(CATALOG_PATH), "-c", statement],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise IngestError(f"DuckDB command failed:\n{result.stderr}\nExecuted SQL:\n{statement}")
    return result


def query_scalar(
    sql: str,
    *,
    duckdb_binary: str,
    env_config: EnvConfig,
    attach_ducklake: bool = False,
    require_httpfs: bool = False,
) -> int:
    """Run a scalar SQL query and parse the resulting integer."""
    statements: List[str] = []
    needs_httpfs = require_httpfs or attach_ducklake or env_config.data_path.startswith(("s3://", "http://", "https://"))
    if needs_httpfs:
        statements.extend(["INSTALL httpfs", "LOAD httpfs"])
        statements.extend(build_s3_statements(env_config))
    if attach_ducklake:
        statements.extend(["INSTALL ducklake", "LOAD ducklake", ducklake_attach_statement(env_config)])
    statements.append(sql)
    if attach_ducklake:
        statements.append("DETACH ducklake")
    result = run_duckdb(statements, duckdb_binary=duckdb_binary)
    return extract_scalar(result.stdout)


def extract_last_value(stdout: str) -> Optional[str]:
    """Extract the final cell value from DuckDB's ASCII table output."""
    for line in reversed(stdout.splitlines()):
        stripped = line.strip()
        if stripped.startswith("│") and stripped.endswith("│"):
            value = stripped.strip("│").strip()
            if value.lower() == "0 rows":
                continue
            return value
    return None


def extract_scalar(stdout: str) -> int:
    """Extract the final integer value from DuckDB's ASCII table output."""
    value = extract_last_value(stdout)
    if value is None or value == "":
        raise IngestError(f"Failed to parse DuckDB output:\n{stdout}")
    try:
        return int(value)
    except ValueError as exc:
        raise IngestError(f"Unexpected non-integer output from DuckDB: '{value}'") from exc


def query_value(
    sql: str,
    *,
    duckdb_binary: str,
    env_config: EnvConfig,
    attach_ducklake: bool = False,
    require_httpfs: bool = False,
) -> Optional[str]:
    """Run a scalar query and return the final cell value as a string."""
    statements: List[str] = []
    needs_httpfs = require_httpfs or attach_ducklake or env_config.data_path.startswith(
        ("s3://", "http://", "https://")
    )
    if needs_httpfs:
        statements.extend(["INSTALL httpfs", "LOAD httpfs"])
        statements.extend(build_s3_statements(env_config))
    if attach_ducklake:
        statements.extend(["INSTALL ducklake", "LOAD ducklake", ducklake_attach_statement(env_config)])
    statements.append(sql)
    if attach_ducklake:
        statements.append("DETACH ducklake")
    result = run_duckdb(statements, duckdb_binary=duckdb_binary)
    return extract_last_value(result.stdout)


def detect_relation_type(
    *,
    schema: str,
    name: str,
    env_config: EnvConfig,
    duckdb_binary: str,
) -> Optional[str]:
    """Return 'TABLE', 'VIEW', or None for a given relation within the ducklake catalog."""
    schema_literal = escape_sql_literal(schema)
    name_literal = escape_sql_literal(name)
    sql = (
        "SELECT table_type FROM information_schema.tables "
        f"WHERE table_catalog='ducklake' "
        f"AND table_schema='{schema_literal}' "
        f"AND table_name='{name_literal}' LIMIT 1"
    )
    value = query_value(sql, duckdb_binary=duckdb_binary, env_config=env_config, attach_ducklake=True)
    if value is None or value == "":
        return None
    normalized = value.upper()
    if normalized in {"BASE TABLE", "TABLE"}:
        return "TABLE"
    if normalized == "VIEW":
        return "VIEW"
    return normalized
