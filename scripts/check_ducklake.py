"""Validation script for DuckLake bootstrap artifacts."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = PROJECT_ROOT / "catalog.db"
EXPECTED_SCHEMAS = ("bronze", "silver", "gold", "audit")
DUCKLAKE_METADATA_PATH = os.getenv("DUCKLAKE_METADATA_PATH", "ducklake/catalog.duckdb")
DUCKLAKE_DATA_PATH = os.getenv("DUCKLAKE_DATA_PATH", "ducklake/data")
METADATA_CATALOG = "__ducklake_metadata_ducklake"


def resolve_path(path_value: str) -> Path:
    """Convert a relative path into an absolute path anchored at the project root."""
    path = Path(path_value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def run_ducklake_query(query: str) -> str:
    """Execute a scalar DuckDB query with DuckLake attached and return stdout."""
    duckdb_binary = shutil.which("duckdb")
    if duckdb_binary is None:
        raise SystemExit("duckdb CLI is required for validation.")

    metadata_path = resolve_path(DUCKLAKE_METADATA_PATH)
    data_path = resolve_path(DUCKLAKE_DATA_PATH)

    statements = [
        "INSTALL ducklake",
        "LOAD ducklake",
        f"ATTACH '{metadata_path}' AS ducklake (TYPE DUCKLAKE, DATA_PATH '{data_path}')",
        query,
        "DETACH ducklake",
    ]
    statement = "; ".join(statements) + ";"
    result = subprocess.run(
        [duckdb_binary, str(CATALOG_PATH), "-c", statement],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"DuckLake validation query failed:\n{result.stderr}\nExecuted SQL:\n{statement}"
        )
    return result.stdout


def extract_scalar(stdout: str) -> int:
    """Pull the final scalar value from DuckDB's ASCII output."""
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("│") and line.endswith("│"):
            value = line.strip("│").strip()
            if not value:
                continue
            try:
                return int(value)
            except ValueError as exc:
                raise SystemExit(f"Unexpected non-integer output: '{value}'") from exc
    raise SystemExit(f"Failed to parse DuckDB output:\n{stdout}")


def validate_catalog() -> None:
    """Verify DuckLake schemas and seed table exist with data."""
    if not CATALOG_PATH.exists():
        raise SystemExit("catalog.db not found. Run `make create_ducklake` first.")

    schema_list = ", ".join(f"'{name}'" for name in EXPECTED_SCHEMAS)
    schema_check_sql = """
        SELECT COUNT(*)
        FROM {metadata_catalog}.ducklake_schema
        WHERE end_snapshot IS NULL
          AND schema_name IN ({schema_list})
    """.format(metadata_catalog=METADATA_CATALOG, schema_list=schema_list)
    schema_count = extract_scalar(run_ducklake_query(schema_check_sql))
    if schema_count != len(EXPECTED_SCHEMAS):
        raise SystemExit(
            f"DuckLake schemas missing: expected {len(EXPECTED_SCHEMAS)}, found {schema_count}."
        )

    table_exists_sql = """
        SELECT COUNT(*)
        FROM {metadata_catalog}.ducklake_table t
        JOIN {metadata_catalog}.ducklake_schema s ON s.schema_id = t.schema_id
        WHERE s.end_snapshot IS NULL
          AND t.end_snapshot IS NULL
          AND s.schema_name = 'bronze'
          AND t.table_name = 'seed_demo'
    """.format(metadata_catalog=METADATA_CATALOG)
    table_count = extract_scalar(run_ducklake_query(table_exists_sql))
    if table_count != 1:
        raise SystemExit("Seed table ducklake.bronze.seed_demo not found.")

    rowcount_sql = "SELECT COUNT(*) FROM ducklake.bronze.seed_demo"
    rowcount = extract_scalar(run_ducklake_query(rowcount_sql))
    if rowcount == 0:
        raise SystemExit("Seed table ducklake.bronze.seed_demo is empty.")


def main() -> int:
    """Entry-point used by Makefile."""
    validate_catalog()
    print("DuckLake schemas and seed dataset verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
