#!/usr/bin/env python3
"""Apply deterministic DuckLake silver/gold transforms (dbt_run surrogate)."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.lib.ducklake_ingest import (
    EnvConfig,
    IngestError,
    build_env_config,
    build_s3_statements,
    detect_relation_type,
    ducklake_attach_statement,
    ensure_duckdb_binary,
    run_duckdb,
)

REQUIRED_SOURCES = [
    ("bronze", "seed_demo"),
    ("bronze", "api_todos"),
    ("bronze", "api_comments"),
    ("bronze", "ecb_exchange_rates"),
]


def validate_sources(*, env_config: EnvConfig, duckdb_binary: str) -> None:
    """Ensure upstream bronze relations exist before building downstream layers."""
    missing: list[str] = []
    for schema, name in REQUIRED_SOURCES:
        relation_type = detect_relation_type(
            schema=schema,
            name=name,
            env_config=env_config,
            duckdb_binary=duckdb_binary,
        )
        if relation_type is None:
            missing.append(f"ducklake.{schema}.{name}")
    if missing:
        bullet_list = "\n- ".join(missing)
        raise IngestError(
            "Transform prerequisites missing. Run the ingestion demo first:\n"
            f"- {bullet_list}"
        )


def build_transform_statements(env_config: EnvConfig) -> list[str]:
    """Return DuckDB SQL statements that materialize silver/gold views."""
    return [
        "INSTALL httpfs",
        "LOAD httpfs",
        "INSTALL ducklake",
        "LOAD ducklake",
        *build_s3_statements(env_config),
        ducklake_attach_statement(env_config),
        "CREATE SCHEMA IF NOT EXISTS ducklake.silver",
        "CREATE SCHEMA IF NOT EXISTS ducklake.gold",
        # Silver models
        "CREATE OR REPLACE VIEW ducklake.silver.seed_demo AS "
        "SELECT id, LOWER(TRIM(name)) AS customer_name, load_timestamp "
        "FROM ducklake.bronze.seed_demo",
        "CREATE OR REPLACE VIEW ducklake.silver.api_todos AS "
        "SELECT CAST(userId AS INTEGER) AS user_id, CAST(id AS INTEGER) AS todo_id, "
        "       completed, load_date, load_batch, title "
        "FROM ducklake.bronze.api_todos",
        "CREATE OR REPLACE VIEW ducklake.silver.api_comments AS "
        "SELECT CAST(postId AS INTEGER) AS post_id, CAST(id AS INTEGER) AS comment_id, "
        "       name, email, body, load_date, load_batch "
        "FROM ducklake.bronze.api_comments",
        "CREATE OR REPLACE VIEW ducklake.silver.ecb_exchange_rates AS "
        "SELECT rate_date, currency_code, currency_name, fx_rate "
        "FROM ducklake.bronze.ecb_exchange_rates",
        # Gold models
        "CREATE OR REPLACE VIEW ducklake.gold.todo_completion_daily AS "
        "SELECT load_date, COUNT(*) AS total_todos, "
        "       SUM(CASE WHEN completed THEN 1 ELSE 0 END) AS completed_todos "
        "FROM ducklake.silver.api_todos "
        "GROUP BY load_date",
        "CREATE OR REPLACE VIEW ducklake.gold.fx_rates_daily AS "
        "SELECT rate_date, "
        "       COUNT(*) AS currency_count, "
        "       AVG(CASE WHEN currency_code = 'USD' THEN fx_rate END) AS eur_to_usd_avg "
        "FROM ducklake.silver.ecb_exchange_rates "
        "GROUP BY rate_date",
        "DETACH ducklake",
    ]


def main() -> int:
    try:
        env_config = build_env_config()
        duckdb_binary = ensure_duckdb_binary(None)
        validate_sources(env_config=env_config, duckdb_binary=duckdb_binary)
        statements = build_transform_statements(env_config)
        run_duckdb(statements, duckdb_binary=duckdb_binary)
    except IngestError as exc:
        print(f"Transforms failed: {exc}", file=sys.stderr)
        return 1
    print("Transforms completed: silver and gold layers refreshed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
