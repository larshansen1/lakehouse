from __future__ import annotations

from typing import List

import scripts.run_transforms as run_transforms
from scripts.lib.ducklake_ingest import EnvConfig


class DummyEnv(EnvConfig):
    def __init__(self):
        super().__init__(
            access_key="key",
            secret_key="secret",
            bucket="lake",
            endpoint_host="localhost:9000",
            endpoint_url="http://localhost:9000",
            use_ssl=False,
            metadata_path=run_transforms.Path("/tmp/catalog.duckdb"),
            data_path="s3://lake/ducklake",
        )


def test_run_transforms_executes_duckdb(monkeypatch):
    env = DummyEnv()
    statements: List[List[str]] = []

    monkeypatch.setattr(run_transforms, "build_env_config", lambda: env)
    monkeypatch.setattr(run_transforms, "ensure_duckdb_binary", lambda _: "duckdb")
    monkeypatch.setattr(run_transforms, "build_s3_statements", lambda _: ["SET test"])
    monkeypatch.setattr(run_transforms, "detect_relation_type", lambda **_: "VIEW")

    def fake_run_duckdb(stmts, duckdb_binary):
        statements.append(stmts)
        statements.append([duckdb_binary])

    monkeypatch.setattr(run_transforms, "run_duckdb", fake_run_duckdb)

    result = run_transforms.main()
    assert result == 0
    assert statements  # ensures run_duckdb was invoked
    sql_statements = statements[0]
    assert any(stmt == "CREATE SCHEMA IF NOT EXISTS ducklake.silver" for stmt in sql_statements)
    assert any(
        stmt.startswith("CREATE OR REPLACE VIEW ducklake.gold.todo_completion_daily")
        for stmt in sql_statements
    )


def test_run_transforms_handles_missing_sources(monkeypatch, capsys):
    env = DummyEnv()
    monkeypatch.setattr(run_transforms, "build_env_config", lambda: env)
    monkeypatch.setattr(run_transforms, "ensure_duckdb_binary", lambda _: "duckdb")

    def missing_relation(**kwargs):
        if kwargs["name"] == "seed_demo":
            return None
        return "VIEW"

    monkeypatch.setattr(run_transforms, "detect_relation_type", missing_relation)

    result = run_transforms.main()
    captured = capsys.readouterr()
    assert result == 1
    assert "Transform prerequisites missing" in captured.err
