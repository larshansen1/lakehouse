#!/usr/bin/env python3
"""List DuckLake archive object paths for manual inspection."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.lib.ducklake_ingest import (
    IngestError,
    build_env_config,
    ensure_duckdb_binary,
    run_duckdb,
)


def parse_args(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--schema",
        default="bronze",
        help="DuckLake schema (default: bronze)",
    )
    parser.add_argument(
        "--table",
        default="ecb_exchange_rates_archive",
        help="DuckLake table name (default: ecb_exchange_rates_archive)",
    )
    return parser.parse_args(argv)


def main(argv) -> int:
    args = parse_args(argv)
    env_config = build_env_config()
    duckdb_binary = ensure_duckdb_binary(None)

    sql = [
        "INSTALL httpfs",
        "LOAD httpfs",
        f"SET s3_endpoint='{env_config.endpoint_host}'",
        "SET s3_url_style='path'",
        f"SET s3_use_ssl={'true' if env_config.use_ssl else 'false'}",
        f"SET s3_access_key_id='{env_config.access_key}'",
        f"SET s3_secret_access_key='{env_config.secret_key}'",
        "INSTALL ducklake",
        "LOAD ducklake",
        f"ATTACH '{env_config.metadata_path.as_posix()}' AS ducklake"
        f" (TYPE DUCKLAKE, DATA_PATH '{env_config.data_path}', OVERRIDE_DATA_PATH true)",
        f"SELECT DISTINCT file_path, file_size_bytes FROM ducklake_table_files('ducklake', '{args.schema}', '{args.table}')",
        "DETACH ducklake",
    ]

    try:
        result = run_duckdb(sql, duckdb_binary=duckdb_binary)
    except IngestError as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        return 1

    print(result.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
