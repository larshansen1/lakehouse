#!/usr/bin/env python3
"""CLI wrapper for API ingestion."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.lib.api_ingest import (  # noqa: E402
    DEFAULT_BUSINESS_KEY,
    DEFAULT_DATASET,
    DEFAULT_ENDPOINT,
    DEFAULT_FILENAME,
    DEFAULT_SAMPLE_SIZE,
    DEFAULT_TABLE,
    ingest_api,
    parse_args,
)
from scripts.lib.ducklake_ingest import (  # noqa: E402
    IngestError,
    build_env_config,
    ensure_duckdb_binary,
)


def main(argv: List[str]) -> int:
    try:
        args = parse_args(argv)
        env_config = build_env_config()
        duckdb_binary = ensure_duckdb_binary(args.duckdb)
        ingest_api(args=args, env_config=env_config, duckdb_binary=duckdb_binary)
    except IngestError as exc:
        print(f"Ingestion failed: {exc}", file=sys.stderr)
        return 1
    return 0


__all__ = [
    "DEFAULT_BUSINESS_KEY",
    "DEFAULT_DATASET",
    "DEFAULT_ENDPOINT",
    "DEFAULT_FILENAME",
    "DEFAULT_SAMPLE_SIZE",
    "DEFAULT_TABLE",
    "ingest_api",
    "main",
    "parse_args",
]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
