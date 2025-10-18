#!/usr/bin/env python3
"""Compute basic row-count telemetry for DuckLake tables."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.lib.ducklake_ingest import (
    EnvConfig,
    IngestError,
    build_env_config,
    build_s3_statements,
    detect_relation_type,
    ducklake_attach_statements,
    ensure_duckdb_binary,
    escape_sql_literal,
    query_scalar,
    run_duckdb,
)

RELATIONS_TO_CHECK: List[Tuple[str, str]] = [
    ("bronze", "seed_demo"),
    ("bronze", "seed_demo_archive"),
    ("bronze", "seed_demo_latest"),
    ("bronze", "api_todos"),
    ("bronze", "api_todos_archive"),
    ("bronze", "api_todos_latest"),
    ("bronze", "api_comments"),
    ("bronze", "api_comments_archive"),
    ("bronze", "api_comments_latest"),
    ("bronze", "ecb_exchange_rates"),
    ("bronze", "ecb_exchange_rates_archive"),
    ("bronze", "ecb_exchange_rates_latest"),
    ("silver", "seed_demo"),
    ("silver", "api_todos"),
    ("silver", "api_comments"),
    ("silver", "ecb_exchange_rates"),
    ("gold", "todo_completion_daily"),
    ("gold", "fx_rates_daily"),
]


def collect_counts(
    *,
    env_config: EnvConfig,
    duckdb_binary: str,
) -> List[Tuple[str, str, int]]:
    """Return available relations with their row counts."""
    counts: List[Tuple[str, str, int]] = []
    for schema, name in RELATIONS_TO_CHECK:
        relation_type = detect_relation_type(
            schema=schema,
            name=name,
            env_config=env_config,
            duckdb_binary=duckdb_binary,
        )
        if relation_type is None:
            continue
        row_count = query_scalar(
            f"SELECT COUNT(*) FROM ducklake.{schema}.{name}",
            duckdb_binary=duckdb_binary,
            env_config=env_config,
            attach_ducklake=True,
        )
        counts.append((schema, name, row_count))
    if not counts:
        raise IngestError("No DuckLake relations found to audit.")
    return counts


def insert_counts(
    counts: Iterable[Tuple[str, str, int]],
    *,
    env_config: EnvConfig,
    duckdb_binary: str,
) -> None:
    """Persist collected counts into ducklake.audit.table_health."""
    timestamp_literal = escape_sql_literal(
        dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(sep=" ")
    )
    values = ",\n        ".join(
        f"('{escape_sql_literal(schema)}', '{escape_sql_literal(name)}', {row_count}, "
        f"TIMESTAMP '{timestamp_literal}')"
        for schema, name, row_count in counts
    )
    statements = [
        "INSTALL httpfs",
        "LOAD httpfs",
        *build_s3_statements(env_config),
        *ducklake_attach_statements(env_config),
        "CREATE SCHEMA IF NOT EXISTS ducklake.audit",
        "CREATE TABLE IF NOT EXISTS ducklake.audit.table_health ("
        "schema_name VARCHAR, relation_name VARCHAR, row_count BIGINT, checked_at TIMESTAMP"
        ")",
    ]
    if values:
        statements.append(
            "INSERT INTO ducklake.audit.table_health "
            "(schema_name, relation_name, row_count, checked_at) VALUES "
            f"{values}"
        )
    statements.append("DETACH ducklake")
    run_duckdb(statements, duckdb_binary=duckdb_binary, env_config=env_config)


def main() -> int:
    try:
        env_config = build_env_config()
        duckdb_binary = ensure_duckdb_binary(None)
        counts = collect_counts(env_config=env_config, duckdb_binary=duckdb_binary)
        insert_counts(counts, env_config=env_config, duckdb_binary=duckdb_binary)
    except IngestError as exc:
        print(f"Audit failed: {exc}", file=sys.stderr)
        return 1
    print("Audit complete: table_health updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
