from __future__ import annotations

from types import SimpleNamespace
from typing import List

import scripts.run_demo as run_demo


def test_run_demo_executes_all_steps(monkeypatch):
    commands: List[List[str]] = []

    def fake_run(cmd, cwd, check):
        commands.append(list(cmd))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_demo.subprocess, "run", fake_run)

    result = run_demo.main([])
    assert result == 0

    expected = [
        ["bash", str(run_demo.SCRIPTS_DIR / "create_ducklake.sh")],
        [run_demo.sys.executable, str(run_demo.SCRIPTS_DIR / "check_ducklake.py")],
        [
            run_demo.sys.executable,
            str(run_demo.SCRIPTS_DIR / "ingest_file.py"),
            "--dataset",
            "seed_demo",
            "--source",
            str(run_demo.SEEDS_DIR / "demo_seed.csv"),
            "--table",
            "seed_demo",
        ],
        [
            run_demo.sys.executable,
            str(run_demo.SCRIPTS_DIR / "ingest_api.py"),
            "--dataset",
            "api/todos",
            "--table",
            "api_todos",
            "--object-name",
            "todos",
            "--endpoint",
            str(run_demo.SEEDS_DIR / "api_todos.json"),
        ],
        [
            run_demo.sys.executable,
            str(run_demo.SCRIPTS_DIR / "ingest_api.py"),
            "--dataset",
            "api/comments",
            "--table",
            "api_comments",
            "--object-name",
            "comments",
            "--endpoint",
            str(run_demo.SEEDS_DIR / "api_comments.json"),
        ],
        [
            run_demo.sys.executable,
            str(run_demo.SCRIPTS_DIR / "ingest_ecb_rates.py"),
            "--endpoint",
            str(run_demo.SEEDS_DIR / "ecb_reference_rates_sample.xml"),
            "--rate-date",
            "2024-01-02",
            "--load-date",
            "2024-01-02",
            "--batch-id",
            "demo-ecb-2024-01-02",
        ],
        [run_demo.sys.executable, str(run_demo.SCRIPTS_DIR / "run_transforms.py")],
        [run_demo.sys.executable, str(run_demo.SCRIPTS_DIR / "run_audit.py")],
    ]
    assert commands == expected


def test_run_demo_stops_on_failure(monkeypatch):
    commands: List[List[str]] = []

    def fake_run(cmd, cwd, check):
        commands.append(list(cmd))
        if "check_ducklake.py" in cmd[-1]:
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_demo.subprocess, "run", fake_run)

    result = run_demo.main([])
    assert result == 1
    assert len(commands) == 2  # bootstrap succeeded, verification failed
