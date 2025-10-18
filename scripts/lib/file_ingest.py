"""Reusable helpers for file-based bronze ingestion."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Optional, Sequence

from scripts.lib.ducklake_ingest import (
    EnvConfig,
    IngestError,
    build_s3_statements,
    detect_relation_type,
    ducklake_attach_statements,
    escape_sql_literal,
    project_root,
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

PROJECT_ROOT = project_root()
DEFAULT_SOURCE = PROJECT_ROOT / "seeds" / "demo_seed.csv"
DEFAULT_DATASET = "seed_demo"
DEFAULT_TABLE = "seed_demo"
DEFAULT_BUSINESS_KEY = "id"


def determine_reader_expression(source_path: Path) -> str:
    """Build the DuckDB SELECT expression that reads the source file."""
    suffix = source_path.suffix.lower()
    escaped = escape_sql_literal(source_path.as_posix())
    if suffix in {".csv", ".tsv"}:
        return f"SELECT * FROM read_csv_auto('{escaped}', header=true)"
    if suffix == ".parquet":
        return f"SELECT * FROM read_parquet('{escaped}')"
    raise IngestError(f"Unsupported file extension '{source_path.suffix}' for {source_path}.")


def build_parser() -> argparse.ArgumentParser:
    """Return an argparse parser for local file ingestion."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        default=DEFAULT_DATASET,
        help=f"Dataset landing prefix (default: {DEFAULT_DATASET})",
    )
    parser.add_argument(
        "--source",
        default=str(DEFAULT_SOURCE),
        help=f"Path to local CSV/Parquet file (default: {DEFAULT_SOURCE})",
    )
    parser.add_argument(
        "--table",
        default=DEFAULT_TABLE,
        help=f"Bronze table name to refresh (default: {DEFAULT_TABLE})",
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
    parser.add_argument(
        "--duckdb",
        help="Optional path to duckdb CLI (overrides DUCKDB env var).",
    )
    return parser


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse command-line arguments for file ingestion."""
    parser = build_parser()
    return parser.parse_args(list(argv))


def ingest_dataset(
    *,
    args: argparse.Namespace,
    env_config: EnvConfig,
    duckdb_binary: str,
) -> None:
    """Perform the full ingestion from local file to bronze table."""
    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        raise IngestError(f"Source file not found: {source_path}")

    dataset = args.dataset.strip("/")
    table_name = args.table or dataset.replace("/", "_")
    load_date = parse_load_date(args.load_date).isoformat()
    batch_id = resolve_batch_id(args.batch_id)
    batch_token = sanitize_for_path(batch_id)
    landing_uri = (
        f"s3://{env_config.bucket}/landing/{dataset}/"
        f"load_date={load_date}/batch_id={batch_token}/{table_name}.parquet"
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

    reader_expression = determine_reader_expression(source_path)
    escaped_uri = escape_sql_literal(landing_uri)
    statements = [
        "INSTALL httpfs",
        "LOAD httpfs",
    ]
    statements.extend(build_s3_statements(env_config))
    statements.append(f"PRAGMA threads={os.cpu_count() or 4}")
    statements.append(
        f"COPY ({reader_expression}) TO '{escaped_uri}' "
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
    archive_ref = f"ducklake.bronze.{archive_table}"
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
        f"FROM {archive_ref} GROUP BY {key_columns_sql}"
        f"), max_load_batch AS ("
        f"SELECT {select_columns_prefixed}, a.load_date, MAX(a.load_batch) AS max_load_batch "
        f"FROM {archive_ref} a JOIN max_load_date m "
        f"ON {key_join_to_max} AND a.load_date = m.max_load_date "
        f"GROUP BY {select_columns_prefixed}, a.load_date"
        f") "
        f"SELECT a.* FROM {archive_ref} a "
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
        f"Ingestion complete for dataset '{dataset}': "
        f"landing rows={landing_count}, archive rows={archive_count}, latest rows={latest_count}, "
        f"load_date={load_date}, load_batch='{batch_id}', object={landing_uri}{note}"
    )


__all__ = [
    "DEFAULT_BUSINESS_KEY",
    "DEFAULT_DATASET",
    "DEFAULT_SOURCE",
    "DEFAULT_TABLE",
    "PROJECT_ROOT",
    "build_parser",
    "determine_reader_expression",
    "ingest_dataset",
    "parse_args",
]
