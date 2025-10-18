"""Reusable helpers for JSON API ingestion flows."""

from __future__ import annotations

import argparse
import os
from typing import Optional, Sequence

from scripts.lib.ducklake_ingest import (
    EnvConfig,
    IngestError,
    build_s3_statements,
    detect_relation_type,
    ducklake_attach_statements,
    escape_sql_literal,
)
from scripts.lib.load_utils import (
    append_drop_statement,
    normalize_business_keys,
    parse_load_date,
    query_scalar_with_retry,
    resolve_batch_id,
    run_duckdb_with_retry,
    sanitize_for_path,
)

DEFAULT_ENDPOINT = "https://jsonplaceholder.typicode.com/todos"
DEFAULT_DATASET = "api/todos"
DEFAULT_TABLE = "api_todos"
DEFAULT_FILENAME = "todos"
DEFAULT_SAMPLE_SIZE = -1  # read full array by default
DEFAULT_BUSINESS_KEY = "id"


def build_parser() -> argparse.ArgumentParser:
    """Return an argparse parser for API ingestion."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help=f"HTTP endpoint to read JSON from (default: {DEFAULT_ENDPOINT})",
    )
    parser.add_argument(
        "--dataset",
        default=DEFAULT_DATASET,
        help=f"Landing prefix under s3://<bucket>/landing/ (default: {DEFAULT_DATASET})",
    )
    parser.add_argument(
        "--table",
        default=DEFAULT_TABLE,
        help=f"Bronze table name to refresh (default: {DEFAULT_TABLE})",
    )
    parser.add_argument(
        "--object-name",
        default=DEFAULT_FILENAME,
        help=f"Filename (without extension) for the landing Parquet object (default: {DEFAULT_FILENAME})",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=DEFAULT_SAMPLE_SIZE,
        help=(
            "Number of rows DuckDB should sample when inferring schema. "
            "Use -1 to inspect the full payload (default: -1)."
        ),
    )
    parser.add_argument(
        "--duckdb",
        help="Optional path to duckdb CLI (overrides DUCKDB env var).",
    )
    parser.add_argument(
        "--load-date",
        help="Optional load date for partitioning (default: current UTC date).",
    )
    parser.add_argument(
        "--batch-id",
        help="Optional batch identifier (default: current UTC timestamp).",
    )
    parser.add_argument(
        "--business-key",
        dest="business_keys",
        action="append",
        help=(
            "Column(s) that define the business key for latest view (default: id). "
            "Provide multiple --business-key values for composite keys."
        ),
    )
    return parser


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse command-line arguments for API ingestion."""
    parser = build_parser()
    return parser.parse_args(list(argv))


def ingest_api(
    *,
    args: argparse.Namespace,
    env_config: EnvConfig,
    duckdb_binary: str,
) -> None:
    """Download the API payload and stage it to landing + bronze."""
    dataset = args.dataset.strip("/")
    table_name = args.table or DEFAULT_TABLE
    object_name = args.object_name or DEFAULT_FILENAME
    load_date = parse_load_date(args.load_date).isoformat()
    batch_id = resolve_batch_id(args.batch_id)
    batch_token = sanitize_for_path(batch_id)
    landing_uri = (
        f"s3://{env_config.bucket}/landing/{dataset}/"
        f"load_date={load_date}/batch_id={batch_token}/{object_name}.parquet"
    )
    archive_table = f"{table_name}_archive"
    latest_view = f"{table_name}_latest"
    load_batch_literal = escape_sql_literal(batch_id)
    archive_relation_type = detect_relation_type(
        schema="bronze",
        name=archive_table,
        env_config=env_config,
        duckdb_binary=duckdb_binary,
    )
    if archive_relation_type is None:
        batch_exists = False
    else:
        try:
            batch_exists = (
                query_scalar_with_retry(
                    f"SELECT COUNT(*) FROM ducklake.bronze.{archive_table} "
                    f"WHERE load_date = DATE '{load_date}' "
                    f"AND load_batch = '{load_batch_literal}'",
                    duckdb_binary=duckdb_binary,
                    env_config=env_config,
                    attach_ducklake=True,
                )
                > 0
            )
        except IngestError as exc:
            if "does not exist" in str(exc).lower():
                batch_exists = False
            else:
                raise

    endpoint = escape_sql_literal(args.endpoint)
    escaped_uri = escape_sql_literal(landing_uri)
    statements = [
        "INSTALL httpfs",
        "LOAD httpfs",
    ]
    statements.extend(build_s3_statements(env_config))
    statements.append(f"PRAGMA threads={os.cpu_count() or 4}")
    json_reader = f"read_json_auto('{endpoint}', sample_size={args.sample_size})"
    statements.append(
        f"COPY (SELECT * FROM {json_reader}) TO '{escaped_uri}' "
        "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 1000000)"
    )
    statements.extend(ducklake_attach_statements(env_config))
    latest_relation_type = detect_relation_type(
        schema="bronze",
        name=latest_view,
        env_config=env_config,
        duckdb_binary=duckdb_binary,
    )
    table_relation_type = detect_relation_type(
        schema="bronze",
        name=table_name,
        env_config=env_config,
        duckdb_binary=duckdb_binary,
    )
    statements.append("CREATE SCHEMA IF NOT EXISTS ducklake.bronze")
    statements.append(
        f"CREATE TABLE IF NOT EXISTS ducklake.bronze.{archive_table} AS "
        f"SELECT CAST(NULL AS DATE) AS load_date, CAST(NULL AS VARCHAR) AS load_batch, t.* "
        f"FROM read_parquet('{escaped_uri}') t WHERE 1=0"
    )
    if not batch_exists:
        statements.append(
            f"INSERT INTO ducklake.bronze.{archive_table} "
            f"SELECT DATE '{load_date}' AS load_date, '{load_batch_literal}' AS load_batch, t.* "
            f"FROM read_parquet('{escaped_uri}') t"
        )
    key_columns = normalize_business_keys(args.business_keys, default=DEFAULT_BUSINESS_KEY)
    key_columns_sql = ", ".join(key_columns)
    select_columns_prefixed = ", ".join(f"a.{col}" for col in key_columns)
    key_join_to_max = " AND ".join(f"a.{col} = m.{col}" for col in key_columns)
    key_join_to_latest = " AND ".join(f"a.{col} = latest.{col}" for col in key_columns)
    append_drop_statement(
        statements, schema="bronze", name=latest_view, relation_type=latest_relation_type
    )
    append_drop_statement(
        statements, schema="bronze", name=table_name, relation_type=table_relation_type
    )
    statements.append(
        f"CREATE OR REPLACE VIEW ducklake.bronze.{latest_view} AS "
        f"WITH max_load_date AS ("
        f"SELECT {key_columns_sql}, MAX(load_date) AS max_load_date "
        f"FROM ducklake.bronze.{archive_table} GROUP BY {key_columns_sql}"
        f"), max_load_batch AS ("
        f"SELECT {select_columns_prefixed}, a.load_date, MAX(a.load_batch) AS max_load_batch "
        f"FROM ducklake.bronze.{archive_table} a JOIN max_load_date m "
        f"ON {key_join_to_max} AND a.load_date = m.max_load_date "
        f"GROUP BY {select_columns_prefixed}, a.load_date"
        f") "
        f"SELECT a.* FROM ducklake.bronze.{archive_table} a "
        f"JOIN max_load_batch latest ON {key_join_to_latest} "
        f"AND a.load_date = latest.load_date "
        f"AND a.load_batch = latest.max_load_batch"
    )
    statements.append(
        f"CREATE OR REPLACE VIEW ducklake.bronze.{table_name} "
        f"AS SELECT * FROM ducklake.bronze.{latest_view}"
    )
    statements.append("DETACH ducklake")
    run_duckdb_with_retry(
        statements,
        duckdb_binary=duckdb_binary,
        env_config=env_config,
    )

    landing_count = query_scalar_with_retry(
        f"SELECT COUNT(*) FROM read_parquet('{escaped_uri}')",
        duckdb_binary=duckdb_binary,
        env_config=env_config,
        require_httpfs=True,
    )
    if batch_exists:
        archive_count: Optional[int] = None
        latest_count: Optional[int] = None
    else:
        archive_count = landing_count
        latest_count = landing_count
    note_parts = []
    if batch_exists:
        note_parts.append("archive unchanged; batch already ingested")
        note_parts.append("archive count not recomputed")
        note_parts.append("latest count not recomputed")
    note = f" ({'; '.join(note_parts)})" if note_parts else ""
    print(
        f"API ingestion complete: endpoint={args.endpoint}, "
        f"landing rows={landing_count}, archive rows={archive_count}, latest rows={latest_count}, "
        f"load_date={load_date}, load_batch='{batch_id}', object={landing_uri}{note}"
    )


__all__ = [
    "DEFAULT_ENDPOINT",
    "DEFAULT_DATASET",
    "DEFAULT_TABLE",
    "DEFAULT_FILENAME",
    "DEFAULT_SAMPLE_SIZE",
    "DEFAULT_BUSINESS_KEY",
    "build_parser",
    "ingest_api",
    "parse_args",
]
