#!/usr/bin/env python3
"""Validate DuckLake archive objects by reading each parquet directly from s3a."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.lib.ducklake_ingest import (
    IngestError,
    build_env_config,
    ducklake_attach_statements,
    ensure_duckdb_binary,
    run_duckdb,
)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "limit",
        nargs="?",
        type=int,
        default=0,
        help="Optional number of failing objects to list (0 = all).",
    )
    return parser.parse_args(list(argv))


def collect_objects(env_config, duckdb_binary: str) -> List[str]:
    """Return all object names referenced by the archive table."""
    sql = [
        "INSTALL httpfs",
        "LOAD httpfs",
        f"SET s3_endpoint='{env_config.endpoint_host}'",
        "SET s3_url_style='path'",
        f"SET s3_use_ssl={'true' if env_config.use_ssl else 'false'}",
        f"SET s3_access_key_id='{env_config.access_key}'",
        f"SET s3_secret_access_key='{env_config.secret_key}'",
        *ducklake_attach_statements(env_config),
        "SELECT DISTINCT file_path FROM ducklake_table_info('ducklake') "
        "WHERE schema_name = 'bronze' AND table_name LIKE 'ecb_exchange_rates%'",
        "DETACH ducklake",
    ]
    result = run_duckdb(sql, duckdb_binary=duckdb_binary, env_config=env_config)
    paths: List[str] = []
    for line in result.stdout.splitlines():
        candidate = line.strip().strip("|").strip()
        if candidate and not candidate.lower().startswith(("ducklake_internal", "ducklake#")):
            paths.append(candidate)
    return paths


def check_object(path: str, env_config, duckdb_binary: str) -> Tuple[str, bool, str]:
    """Attempt to read the object; return (path, ok, error_message)."""
    sql = [
        "INSTALL httpfs",
        "LOAD httpfs",
        f"SET s3_endpoint='{env_config.endpoint_host}'",
        "SET s3_url_style='path'",
        f"SET s3_use_ssl={'true' if env_config.use_ssl else 'false'}",
        f"SET s3_access_key_id='{env_config.access_key}'",
        f"SET s3_secret_access_key='{env_config.secret_key}'",
        f"SELECT COUNT(*) FROM read_parquet('s3://{path}')",
    ]
    try:
        run_duckdb(sql, duckdb_binary=duckdb_binary, env_config=env_config)
        return path, True, ""
    except IngestError as exc:
        return path, False, str(exc)


def main(argv: Iterable[str]) -> int:
    args = parse_args(list(argv))
    env_config = build_env_config()
    duckdb_binary = ensure_duckdb_binary(os.getenv("DUCKDB"))

    print("Scanning DuckLake archive object references...")
    objects = collect_objects(env_config, duckdb_binary)
    total = len(objects)
    print(f"Found {total} object references.")

    failures: List[Tuple[str, str]] = []
    for idx, path in enumerate(objects, start=1):
        normalized = path.replace("s3://", "").strip("/")
        print(f"[{idx}/{total}] Checking {normalized}...", end="\r")
        _, ok, error = check_object(normalized, env_config, duckdb_binary)
        if not ok:
            failures.append((normalized, error))
            print(f"[FAIL] {normalized}: {error}")
        elif args.limit and len(failures) >= args.limit:
            break
    print()

    if failures:
        print("Objects that failed to read:")
        for path, error in failures[: args.limit or None]:
            print(f"- {path}\n  {error}")
        if args.limit and len(failures) > args.limit:
            print(f"... {len(failures) - args.limit} additional failures omitted.")
        return 1

    print("All referenced archive objects were readable.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
