#!/usr/bin/env python3
"""Validation script for DuckLake bootstrap artifacts."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.lib.ducklake_ingest import (
    IngestError,
    build_env_config,
    build_s3_statements,
    ducklake_attach_statements,
    ensure_duckdb_binary,
    extract_scalar,
    project_root,
    run_duckdb,
)

PROJECT_ROOT = project_root()
CATALOG_PATH = PROJECT_ROOT / "catalog.db"
EXPECTED_SCHEMAS = ("bronze", "silver", "gold", "audit")
METADATA_CATALOG = "__ducklake_metadata_ducklake"
ENV_CONFIG = build_env_config()
DUCKDB_BIN = ensure_duckdb_binary(None)


def run_ducklake_query(query: str) -> int:
    """Execute a scalar DuckDB query with DuckLake attached and return the integer result."""
    statements = [
        "INSTALL httpfs",
        "LOAD httpfs",
        *build_s3_statements(ENV_CONFIG),
        *ducklake_attach_statements(ENV_CONFIG),
        query,
        "DETACH ducklake",
    ]
    result = run_duckdb(
        statements,
        duckdb_binary=DUCKDB_BIN,
        env_config=ENV_CONFIG,
    )
    return extract_scalar(result.stdout)


def validate_catalog() -> None:
    """Verify DuckLake schemas and seed table exist with data."""
    if ENV_CONFIG.backend != "postgres" and not CATALOG_PATH.exists():
        raise SystemExit("catalog.db not found. Run `make create_ducklake` first.")

    schema_list = ", ".join(f"'{name}'" for name in EXPECTED_SCHEMAS)
    schema_check_sql = f"""
        SELECT COUNT(*)
        FROM {METADATA_CATALOG}.ducklake_schema
        WHERE end_snapshot IS NULL
          AND schema_name IN ({schema_list})
    """
    schema_count = run_ducklake_query(schema_check_sql)
    if schema_count != len(EXPECTED_SCHEMAS):
        raise SystemExit(
            f"DuckLake schemas missing: expected {len(EXPECTED_SCHEMAS)}, found {schema_count}."
        )

    table_exists_sql = f"""
        SELECT COUNT(*)
        FROM {METADATA_CATALOG}.ducklake_table t
        JOIN {METADATA_CATALOG}.ducklake_schema s ON s.schema_id = t.schema_id
        WHERE s.end_snapshot IS NULL
          AND t.end_snapshot IS NULL
          AND s.schema_name = 'bronze'
          AND t.table_name = 'seed_demo_archive'
    """
    table_count = run_ducklake_query(table_exists_sql)
    if table_count != 1:
        raise SystemExit("Seed archive table ducklake.bronze.seed_demo_archive not found.")

    rowcount_sql = "SELECT COUNT(*) FROM ducklake.bronze.seed_demo"
    rowcount = run_ducklake_query(rowcount_sql)
    if rowcount == 0:
        raise SystemExit("Seed table ducklake.bronze.seed_demo is empty.")


def main() -> int:
    """Entry-point used by Makefile."""
    try:
        validate_catalog()
    except IngestError as exc:
        raise SystemExit(f"DuckLake validation query failed: {exc}") from exc
    print("DuckLake schemas and seed dataset verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
