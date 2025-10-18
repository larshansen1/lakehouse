#!/usr/bin/env python3
"""Fetch ECB reference exchange rates and load them into DuckLake bronze archive."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
import os
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Dict, Iterable, List, Optional
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from urllib.parse import urlparse, unquote

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.lib.ducklake_ingest import (
    EnvConfig,
    IngestError,
    build_env_config,
    build_s3_statements,
    ducklake_attach_statement,
    detect_relation_type,
    ensure_duckdb_binary,
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

DEFAULT_ENDPOINT = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
DEFAULT_DATASET = "public/ecb_exchange_rates"
DEFAULT_TABLE = "ecb_exchange_rates"
DEFAULT_OBJECT = "rates"
DEFAULT_BUSINESS_KEY = "currency_code"
ECB_BASE_CURRENCY = "EUR"

# Selected subset of ISO currency names for readability.
CURRENCY_NAMES: Dict[str, str] = {
    "AUD": "Australian Dollar",
    "BGN": "Bulgarian Lev",
    "BRL": "Brazilian Real",
    "CAD": "Canadian Dollar",
    "CHF": "Swiss Franc",
    "CNY": "Chinese Yuan",
    "CZK": "Czech Koruna",
    "DKK": "Danish Krone",
    "EUR": "Euro",
    "GBP": "British Pound Sterling",
    "HKD": "Hong Kong Dollar",
    "HUF": "Hungarian Forint",
    "IDR": "Indonesian Rupiah",
    "ILS": "Israeli Shekel",
    "INR": "Indian Rupee",
    "ISK": "Icelandic Krona",
    "JPY": "Japanese Yen",
    "KRW": "South Korean Won",
    "MXN": "Mexican Peso",
    "MYR": "Malaysian Ringgit",
    "NOK": "Norwegian Krone",
    "NZD": "New Zealand Dollar",
    "PHP": "Philippine Peso",
    "PLN": "Polish Zloty",
    "RON": "Romanian Leu",
    "SEK": "Swedish Krona",
    "SGD": "Singapore Dollar",
    "THB": "Thai Baht",
    "TRY": "Turkish Lira",
    "USD": "US Dollar",
    "ZAR": "South African Rand",
}


@dataclass(slots=True)
class RateRecord:
    rate_date: dt.date
    currency_code: str
    fx_rate: Decimal
    currency_name: Optional[str]


def fetch_ecb_rates(endpoint: str) -> str:
    """Retrieve ECB XML payload from the given endpoint."""
    parsed = urlparse(endpoint)
    if parsed.scheme in {"", "file"}:
        if parsed.scheme == "file":
            local_path = Path(unquote(parsed.path or ""))
        else:
            local_path = Path(endpoint)
        if not local_path.exists():
            raise IngestError(f"Local ECB XML file not found: {local_path}")
        return local_path.read_text(encoding="utf-8")

    request = Request(endpoint, headers={"User-Agent": "ducklake-ingest/1.0"})
    try:
        with urlopen(request, timeout=30) as response:  # nosec B310 - controlled URL
            status = getattr(response, "status", 200)
            if status != 200:
                raise IngestError(f"ECB endpoint returned HTTP {status}")
            return response.read().decode("utf-8")
    except Exception as exc:  # pragma: no cover - network exceptions captured
        raise IngestError(f"Failed to fetch ECB exchange rates from {endpoint}: {exc}") from exc


def parse_rate_date(value: Optional[str]) -> Optional[dt.date]:
    """Parse the requested rate date, allowing None for 'latest available'."""
    if value is None:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise IngestError(
            f"Invalid --rate-date '{value}'. Expected ISO format YYYY-MM-DD."
        ) from exc


def parse_ecb_xml(xml_text: str) -> Dict[dt.date, List[RateRecord]]:
    """Convert ECB XML feed into a dictionary keyed by rate date."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise IngestError(f"Unable to parse ECB XML payload: {exc}") from exc

    records: Dict[dt.date, List[RateRecord]] = {}
    for time_cube in root.findall(".//{*}Cube[@time]"):
        time_attr = time_cube.attrib.get("time")
        if not time_attr:
            continue
        try:
            rate_date = dt.date.fromisoformat(time_attr)
        except ValueError:
            continue
        daily_rates: List[RateRecord] = []
        for rate_cube in time_cube.findall("{*}Cube[@currency][@rate]"):
            currency = rate_cube.attrib["currency"].upper()
            rate_value = rate_cube.attrib["rate"]
            try:
                fx_rate = Decimal(rate_value)
            except (InvalidOperation, KeyError):
                continue
            daily_rates.append(
                RateRecord(
                    rate_date=rate_date,
                    currency_code=currency,
                    fx_rate=fx_rate,
                    currency_name=CURRENCY_NAMES.get(currency),
                )
            )
        daily_rates.append(
            RateRecord(
                rate_date=rate_date,
                currency_code=ECB_BASE_CURRENCY,
                fx_rate=Decimal("1.0"),
                currency_name=CURRENCY_NAMES.get(ECB_BASE_CURRENCY),
            )
        )
        records[rate_date] = daily_rates
    if not records:
        raise IngestError("No exchange-rate observations found in ECB payload.")
    return records


def select_rate_batch(
    observations: Dict[dt.date, List[RateRecord]],
    desired_date: Optional[dt.date],
) -> tuple[dt.date, List[RateRecord]]:
    """Choose the rate batch for the requested date (default: max available)."""
    if desired_date is not None:
        if desired_date not in observations:
            available = ", ".join(sorted(d.isoformat() for d in observations.keys()))
            raise IngestError(
                f"Requested rate date {desired_date.isoformat()} not found in ECB feed. "
                f"Available dates: {available}"
            )
        return desired_date, observations[desired_date]
    latest_date = max(observations.keys())
    return latest_date, observations[latest_date]


def build_values_sql(rows: Iterable[RateRecord]) -> str:
    """Generate the VALUES clause used to stage data via DuckDB."""
    values_sql: List[str] = []
    for row in rows:
        rate_date = row.rate_date.isoformat()
        currency_literal = escape_sql_literal(row.currency_code)
        if row.currency_name:
            name_literal = f"'{escape_sql_literal(row.currency_name)}'"
        else:
            name_literal = "NULL"
        fx_literal = f"{row.fx_rate.normalize():f}"
        values_sql.append(
            f"(DATE '{rate_date}', '{currency_literal}', {name_literal}, {fx_literal})"
        )
    if not values_sql:
        raise IngestError("No exchange-rate rows available to ingest.")
    return ",\n        ".join(values_sql)


def ingest_ecb_rates(
    *,
    args: argparse.Namespace,
    env_config: EnvConfig,
    duckdb_binary: str,
) -> None:
    """Download ECB rates and load them into landing + bronze archive tables."""
    dataset = args.dataset.strip("/")
    table_name = args.table or DEFAULT_TABLE
    object_name = args.object_name or DEFAULT_OBJECT

    feed_text = fetch_ecb_rates(args.endpoint)
    observations = parse_ecb_xml(feed_text)
    desired_rate_date = parse_rate_date(args.rate_date)
    rate_date, rate_rows = select_rate_batch(observations, desired_rate_date)

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

    values_sql = build_values_sql(rate_rows)
    duckdb_statements = [
        "INSTALL httpfs",
        "LOAD httpfs",
        "INSTALL ducklake",
        "LOAD ducklake",
    ]
    duckdb_statements.extend(build_s3_statements(env_config))
    duckdb_statements.append(f"PRAGMA threads={os.cpu_count() or 4}")
    duckdb_statements.append(
        f"COPY (SELECT * FROM (VALUES {values_sql}) "
        "AS v(rate_date, currency_code, currency_name, fx_rate)) "
        f"TO '{escape_sql_literal(landing_uri)}' "
        "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 1000000)"
    )
    duckdb_statements.append(ducklake_attach_statement(env_config))

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

    duckdb_statements.append("CREATE SCHEMA IF NOT EXISTS ducklake.bronze")
    duckdb_statements.append(
        f"CREATE TABLE IF NOT EXISTS ducklake.bronze.{archive_table} AS "
        "SELECT CAST(NULL AS DATE) AS load_date, "
        "CAST(NULL AS VARCHAR) AS load_batch, "
        "CAST(NULL AS DATE) AS rate_date, "
        "CAST(NULL AS VARCHAR) AS currency_code, "
        "CAST(NULL AS VARCHAR) AS currency_name, "
        "CAST(NULL AS DECIMAL(18,6)) AS fx_rate "
        "WHERE 1=0"
    )
    if not batch_exists:
        duckdb_statements.append(
            f"INSERT INTO ducklake.bronze.{archive_table} "
            f"SELECT DATE '{load_date}' AS load_date, "
            f"'{load_batch_literal}' AS load_batch, "
            "t.rate_date, t.currency_code, t.currency_name, t.fx_rate "
            f"FROM read_parquet('{escape_sql_literal(landing_uri)}') t"
        )

    key_columns = normalize_business_keys(args.business_keys, default=DEFAULT_BUSINESS_KEY)
    key_columns_sql = ", ".join(key_columns)
    append_drop_statement(
        duckdb_statements,
        schema="bronze",
        name=latest_view,
        relation_type=latest_relation_type,
    )
    append_drop_statement(
        duckdb_statements,
        schema="bronze",
        name=table_name,
        relation_type=table_relation_type,
    )
    duckdb_statements.append(
        f"CREATE OR REPLACE VIEW ducklake.bronze.{latest_view} AS "
        f"SELECT a.* FROM ducklake.bronze.{archive_table} a "
        f"QUALIFY ROW_NUMBER() OVER (PARTITION BY {key_columns_sql} "
        f"ORDER BY rate_date DESC, load_date DESC, load_batch DESC) = 1"
    )
    duckdb_statements.append(
        f"CREATE OR REPLACE VIEW ducklake.bronze.{table_name} "
        f"AS SELECT * FROM ducklake.bronze.{latest_view}"
    )
    duckdb_statements.append("DETACH ducklake")
    run_duckdb_with_retry(duckdb_statements, duckdb_binary=duckdb_binary)

    landing_count = len(rate_rows)
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
        f"ECB ingestion complete: rate_date={rate_date.isoformat()}, "
        f"landing rows={landing_count}, archive rows={archive_count}, "
        f"latest rows={latest_count}, load_date={load_date}, "
        f"load_batch='{batch_id}', object={landing_uri}{note}"
    )


def parse_args(argv: List[str]) -> argparse.Namespace:
    """Configure CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help=f"ECB XML endpoint to read (default: {DEFAULT_ENDPOINT})",
    )
    parser.add_argument(
        "--dataset",
        default=DEFAULT_DATASET,
        help="Landing prefix under s3://<bucket>/landing/ (default: public/ecb_exchange_rates)",
    )
    parser.add_argument(
        "--table",
        default=DEFAULT_TABLE,
        help="Bronze table name to refresh (default: ecb_exchange_rates)",
    )
    parser.add_argument(
        "--object-name",
        default=DEFAULT_OBJECT,
        help="Filename (without extension) for the landing Parquet object (default: rates)",
    )
    parser.add_argument(
        "--rate-date",
        help="Business date (YYYY-MM-DD) to ingest; defaults to latest published.",
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
            "Column(s) that define the business key for latest view "
            "(default: currency_code). Provide multiple --business-key values for composite keys."
        ),
    )
    parser.add_argument(
        "--duckdb",
        default=os.getenv("DUCKDB"),
        help="Optional path to duckdb CLI (overrides DUCKDB env var).",
    )
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    """Entrypoint executed by CLI and automation."""
    try:
        args = parse_args(argv)
        env_config = build_env_config()
        duckdb_binary = ensure_duckdb_binary(args.duckdb)
        ingest_ecb_rates(args=args, env_config=env_config, duckdb_binary=duckdb_binary)
    except IngestError as exc:
        print(f"Ingestion failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
