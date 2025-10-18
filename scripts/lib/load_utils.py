"""Shared helpers for ingestion scripts handling load metadata."""

from __future__ import annotations

import datetime as dt
import re
import time
from typing import Iterable, List, Optional

from scripts.lib.ducklake_ingest import IngestError, query_scalar, run_duckdb

SAFE_TOKEN_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _utc_now() -> dt.datetime:
    """Return current UTC time with timezone awareness."""
    return dt.datetime.now(tz=dt.timezone.utc)


def parse_load_date(value: Optional[str]) -> dt.date:
    """Validate and normalize the load date (defaults to current UTC date)."""
    if value is None:
        return _utc_now().date()
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise IngestError(
            f"Invalid --load-date '{value}'. Expected ISO format YYYY-MM-DD."
        ) from exc


def resolve_batch_id(value: Optional[str]) -> str:
    """Determine the batch identifier string used for archive metadata."""
    if value is None or value.strip() == "":
        return _utc_now().replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    batch_id = value.strip()
    if not batch_id:
        raise IngestError("Batch identifier cannot be empty after trimming whitespace.")
    return batch_id


def sanitize_for_path(value: str) -> str:
    """Convert potentially unsafe tokens into S3-friendly path segments."""
    cleaned = SAFE_TOKEN_PATTERN.sub("-", value).strip("-")
    return cleaned or "batch"


def ensure_valid_identifier(value: str) -> str:
    """Ensure column identifiers are DuckDB-safe (alphanumeric + underscore)."""
    if not IDENTIFIER_PATTERN.match(value):
        raise IngestError(
            f"Invalid identifier '{value}'. Use snake_case column names without spaces or punctuation."
        )
    return value


def normalize_business_keys(values: Optional[Iterable[str]], *, default: str) -> List[str]:
    """Parse CLI-provided business keys, falling back to a default when absent."""
    keys: List[str] = []
    if values:
        for entry in values:
            if entry is None:
                continue
            parts = [item.strip() for item in entry.split(",") if item and item.strip()]
            for part in parts:
                keys.append(ensure_valid_identifier(part))
    if not keys:
        keys = [ensure_valid_identifier(default)]
    return keys


def query_scalar_with_retry(
    sql: str,
    *,
    duckdb_binary: str,
    env_config,
    attach_ducklake: bool = False,
    require_httpfs: bool = False,
    attempts: int = 3,
    delay_seconds: float = 1.0,
) -> int:
    """Run query_scalar with simple retry logic to handle transient I/O failures."""
    last_exc: IngestError | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return query_scalar(
                sql,
                duckdb_binary=duckdb_binary,
                env_config=env_config,
                attach_ducklake=attach_ducklake,
                require_httpfs=require_httpfs,
            )
        except IngestError as exc:
            last_exc = exc
            if attempt >= attempts:
                break
            time.sleep(delay_seconds * attempt)
    assert last_exc is not None
    raise last_exc


def run_duckdb_with_retry(
    statements: Iterable[str],
    *,
    duckdb_binary: str,
    env_config=None,
    database=None,
    attempts: int = 3,
    delay_seconds: float = 1.0,
):
    """Execute DuckDB statements with simple retry on transient HTTP errors."""
    last_exc: IngestError | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return run_duckdb(
                statements,
                duckdb_binary=duckdb_binary,
                env_config=env_config,
                database=database,
            )
        except IngestError as exc:
            lower = str(exc).lower()
            if "http" not in lower or attempt >= attempts:
                raise
            last_exc = exc
            time.sleep(delay_seconds * attempt)
    assert last_exc is not None
    raise last_exc


def append_drop_statement(
    statements: List[str],
    *,
    schema: str,
    name: str,
    relation_type: Optional[str],
) -> None:
    """Append the correct DROP statement for an existing relation."""
    qualified = f"ducklake.{schema}.{name}"
    if relation_type == "VIEW":
        statements.append(f"DROP VIEW IF EXISTS {qualified}")
    elif relation_type in {"TABLE", "BASE TABLE"}:
        statements.append(f"DROP TABLE IF EXISTS {qualified}")
