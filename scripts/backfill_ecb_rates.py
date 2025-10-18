#!/usr/bin/env python3
"""Backfill ECB exchange rates for a given year using the standard ingest pipeline."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional, Sequence
import subprocess

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.ingest_ecb_rates import fetch_ecb_rates, parse_ecb_xml
from scripts.lib.ducklake_ingest import IngestError


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("year", type=int, help="Calendar year to backfill (e.g., 2023).")
    parser.add_argument(
        "--endpoint",
        default="https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml",
        help=(
            "ECB XML endpoint to source data from. Defaults to the full historical feed "
            "(recommended for backfills)."
        ),
    )
    parser.add_argument(
        "--duckdb",
        help="Optional path to the duckdb CLI (forwarded to ingest script via --duckdb).",
    )
    parser.add_argument(
        "--batch-prefix",
        default="backfill",
        help="String used to build batch identifiers (default: backfill).",
    )
    parser.add_argument(
        "--start-date",
        help="Optional inclusive lower bound (YYYY-MM-DD) within the target year.",
    )
    parser.add_argument(
        "--end-date",
        help="Optional inclusive upper bound (YYYY-MM-DD) within the target year.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the dates that would be ingested without executing them.",
    )
    return parser.parse_args(argv)


def parse_date(value: Optional[str], *, default_year: int, label: str) -> Optional[dt.date]:
    if value is None:
        return None
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise IngestError(f"Invalid {label} '{value}'. Expected ISO format YYYY-MM-DD.") from exc
    if parsed.year != default_year:
        raise IngestError(f"{label} {parsed} is outside the requested year {default_year}.")
    return parsed


def filter_dates(
    all_dates: Iterable[dt.date],
    *,
    year: int,
    start: Optional[dt.date],
    end: Optional[dt.date],
) -> List[dt.date]:
    selected = [d for d in all_dates if d.year == year]
    selected.sort()
    if not selected:
        raise IngestError(f"No ECB rate dates were found for year {year}.")
    if start:
        selected = [d for d in selected if d >= start]
    if end:
        selected = [d for d in selected if d <= end]
    if not selected:
        raise IngestError(
            f"No ECB rate dates remain after applying range filters "
            f"(start={start}, end={end})."
        )
    return selected


def materialize_endpoint(xml_text: str) -> Path:
    """Write XML payload to a temporary file for repeated ingestion."""
    tmp = tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False)
    try:
        tmp.write(xml_text)
        tmp.flush()
        return Path(tmp.name).resolve()
    finally:
        tmp.close()


def run_ingest(
    *,
    date: dt.date,
    endpoint_uri: str,
    duckdb_binary: Optional[str],
    batch_prefix: str,
) -> int:
    command: List[str] = [
        sys.executable,
        str(Path(__file__).resolve().parents[0] / "ingest_ecb_rates.py"),
        "--endpoint",
        endpoint_uri,
        "--rate-date",
        date.isoformat(),
        "--load-date",
        date.isoformat(),
        "--batch-id",
        f"{batch_prefix}-{date.isoformat()}",
    ]
    if duckdb_binary:
        command.extend(["--duckdb", duckdb_binary])
    completed = subprocess.run(command, check=False)
    return completed.returncode


def main(argv: Sequence[str]) -> int:
    try:
        args = parse_args(argv)
        start_date = parse_date(args.start_date, default_year=args.year, label="start-date")
        end_date = parse_date(args.end_date, default_year=args.year, label="end-date")

        xml_text = fetch_ecb_rates(args.endpoint)
        observations = parse_ecb_xml(xml_text)
        all_dates = filter_dates(observations.keys(), year=args.year, start=start_date, end=end_date)

        if args.dry_run:
            print("ECB backfill dry-run. Dates to ingest:")
            for date in all_dates:
                print(f"  {date.isoformat()}")
            return 0

        xml_path = materialize_endpoint(xml_text)
        try:
            endpoint_uri = xml_path.as_uri()
            print(
                f"Prepared ECB data from {args.endpoint} -> {endpoint_uri}. "
                f"Ingesting {len(all_dates)} day(s) for year {args.year}."
            )

            failures: List[dt.date] = []
            reloaded = False
            for index, rate_date in enumerate(all_dates, start=1):
                print(f"[{index}/{len(all_dates)}] Ingesting {rate_date.isoformat()}...")
                code = run_ingest(
                    date=rate_date,
                    endpoint_uri=endpoint_uri,
                    duckdb_binary=args.duckdb,
                    batch_prefix=args.batch_prefix,
                )
                if code != 0:
                    print(f"  -> Failed with exit code {code}", file=sys.stderr)
                    failures.append(rate_date)
                else:
                    print("  -> Success")
                    reloaded = True

            if failures:
                print("Backfill completed with errors.", file=sys.stderr)
                print("Failed dates:", ", ".join(d.isoformat() for d in failures), file=sys.stderr)
                return 1
            if not reloaded:
                print(
                    "No batches were reloaded (existing snapshots already present for the requested range)."
                )

            print("Backfill completed successfully.")
            return 0
        finally:
            try:
                xml_path.unlink(missing_ok=True)
            except OSError:
                pass
    except IngestError as exc:
        print(f"Backfill failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
