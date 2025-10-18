#!/usr/bin/env python3
"""CLI wrapper for ECB reference rate ingestion."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.lib.ducklake_ingest import (  # noqa: E402
    IngestError,
    build_env_config,
    ensure_duckdb_binary,
)
from scripts.lib.ecb_rates_ingest import (  # noqa: E402
    RateRecord,
    build_values_sql,
    fetch_ecb_rates,
    ingest_ecb_rates,
    parse_args,
    parse_ecb_xml,
    parse_rate_date,
    select_rate_batch,
)


def main(argv: List[str]) -> int:
    try:
        args = parse_args(argv)
        env_config = build_env_config()
        duckdb_binary = ensure_duckdb_binary(args.duckdb)
        ingest_ecb_rates(args=args, env_config=env_config, duckdb_binary=duckdb_binary)
    except IngestError as exc:
        print(f"Ingestion failed: {exc}", file=sys.stderr)
        return 1
    return 0


__all__ = [
    "RateRecord",
    "build_values_sql",
    "fetch_ecb_rates",
    "main",
    "parse_args",
    "parse_ecb_xml",
    "parse_rate_date",
    "select_rate_batch",
]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
