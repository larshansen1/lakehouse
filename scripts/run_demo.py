#!/usr/bin/env python3
"""End-to-end demo runner orchestrating bootstrap, ingestion, transforms, and audit."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
SEEDS_DIR = PROJECT_ROOT / "seeds"


def run_step(description: str, command: list[str]) -> None:
    """Execute a shell command and surface failures with context."""
    print(f"[demo] {description} ...")
    result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{description} failed with exit code {result.returncode}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-bootstrap",
        action="store_true",
        help="Skip the DuckLake bootstrap step (assume environment already prepared).",
    )
    parser.add_argument(
        "--skip-transforms",
        action="store_true",
        help="Skip the transformation stage (silver/gold views).",
    )
    parser.add_argument(
        "--skip-audit",
        action="store_true",
        help="Skip writing audit row counts after ingestion completes.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    try:
        if not args.skip_bootstrap:
            run_step(
                "Bootstrapping DuckLake catalog",
                ["bash", str(SCRIPTS_DIR / "create_ducklake.sh")],
            )
            run_step(
                "Verifying DuckLake schemas",
                [sys.executable, str(SCRIPTS_DIR / "check_ducklake.py")],
            )

        run_step(
            "Ingesting seed_demo dataset",
            [
                sys.executable,
                str(SCRIPTS_DIR / "ingest_file.py"),
                "--dataset",
                "seed_demo",
                "--source",
                str(SEEDS_DIR / "demo_seed.csv"),
                "--table",
                "seed_demo",
            ],
        )
        run_step(
            "Ingesting API todos snapshot",
            [
                sys.executable,
                str(SCRIPTS_DIR / "ingest_api.py"),
                "--dataset",
                "api/todos",
                "--table",
                "api_todos",
                "--object-name",
                "todos",
                "--endpoint",
                str(SEEDS_DIR / "api_todos.json"),
            ],
        )
        run_step(
            "Ingesting API comments snapshot",
            [
                sys.executable,
                str(SCRIPTS_DIR / "ingest_api.py"),
                "--dataset",
                "api/comments",
                "--table",
                "api_comments",
                "--object-name",
                "comments",
                "--endpoint",
                str(SEEDS_DIR / "api_comments.json"),
            ],
        )
        run_step(
            "Ingesting ECB reference rates snapshot",
            [
                sys.executable,
                str(SCRIPTS_DIR / "ingest_ecb_rates.py"),
                "--endpoint",
                str(SEEDS_DIR / "ecb_reference_rates_sample.xml"),
                "--rate-date",
                "2024-01-02",
                "--load-date",
                "2024-01-02",
                "--batch-id",
                "demo-ecb-2024-01-02",
            ],
        )

        if not args.skip_transforms:
            run_step(
                "Running silver/gold transforms",
                [sys.executable, str(SCRIPTS_DIR / "run_transforms.py")],
            )

        if not args.skip_audit:
            run_step(
                "Recording audit row counts",
                [sys.executable, str(SCRIPTS_DIR / "run_audit.py")],
            )
    except RuntimeError as exc:
        print(f"[demo] {exc}", file=sys.stderr)
        return 1

    print("[demo] Completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
