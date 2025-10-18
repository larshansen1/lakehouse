#!/usr/bin/env python3
"""Launch an interactive DuckDB shell preconfigured for DuckLake + MinIO access."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.lib.ducklake_ingest import (
    EnvConfig,
    IngestError,
    build_env_config,
    catalog_path,
    ducklake_attach_statements,
    ensure_duckdb_binary,
    escape_sql_literal,
)


def build_shell_commands() -> tuple[List[str], EnvConfig]:
    """Return the canonical set of SQL statements to configure DuckLake access."""
    env_config = build_env_config()
    escaped_endpoint = escape_sql_literal(env_config.endpoint_host)
    escaped_access = escape_sql_literal(env_config.access_key)
    escaped_secret = escape_sql_literal(env_config.secret_key)
    ssl_flag = "true" if env_config.use_ssl else "false"
    catalog_statements = [f"{statement};" for statement in ducklake_attach_statements(env_config)]
    commands = [
        "INSTALL httpfs;",
        "LOAD httpfs;",
        f"SET s3_endpoint='{escaped_endpoint}';",
        "SET s3_url_style='path';",
        f"SET s3_use_ssl={ssl_flag};",
        f"SET s3_access_key_id='{escaped_access}';",
        f"SET s3_secret_access_key='{escaped_secret}';",
        *catalog_statements,
        "USE ducklake;",
    ]
    return commands, env_config


def launch_shell(duckdb_binary: str) -> int:
    """Execute the DuckDB CLI with pre-seeded commands."""
    try:
        commands, env_config = build_shell_commands()
    except IngestError as exc:
        print(f"Failed to load environment configuration: {exc}", file=sys.stderr)
        return 1

    database_target = ":memory:" if env_config.backend == "postgres" else str(catalog_path())
    args: List[str] = [duckdb_binary, database_target, "-interactive"]
    readonly_mode = env_config.backend == "postgres"
    for command in commands:
        args.extend(["-cmd", command])
    if readonly_mode:
        args.extend(["-cmd", "SET enable_external_access=false;"])

    print("Launching duckdb shell with DuckLake configuration...")
    print("Pre-executed commands:")
    for command in commands:
        display = command
        if "SET s3_secret_access_key" in command:
            display = "SET s3_secret_access_key='***masked***';"
        print(f"  {display}")
    print("Type '.quit' to exit.")
    return subprocess.call(args, cwd=catalog_path().parent)


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--duckdb",
        default=os.getenv("DUCKDB"),
        help="Optional path to duckdb CLI (overrides DUCKDB env var).",
    )
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    try:
        duckdb_binary = ensure_duckdb_binary(args.duckdb)
    except IngestError as exc:
        print(f"Failed to locate duckdb CLI: {exc}", file=sys.stderr)
        return 1
    return launch_shell(duckdb_binary)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
