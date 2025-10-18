from __future__ import annotations

import scripts.run_audit as run_audit
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
            metadata_path=run_audit.Path("/tmp/catalog.duckdb"),
            data_path="s3://lake/ducklake",
        )


def test_run_audit_collects_counts(monkeypatch, capsys):
    env = DummyEnv()
    monkeypatch.setattr(run_audit, "build_env_config", lambda: env)
    monkeypatch.setattr(run_audit, "ensure_duckdb_binary", lambda _: "duckdb")

    available = {
        ("bronze", "seed_demo"): 3,
        ("gold", "todo_completion_daily"): 2,
    }

    def fake_detect_relation_type(schema, name, **_):
        return "TABLE" if (schema, name) in available else None

    def fake_query_scalar(sql, **_):
        for (schema, name), count in available.items():
            if f"ducklake.{schema}.{name}" in sql:
                return count
        raise AssertionError("Unexpected query")

    inserted = {}

    def fake_run_duckdb(statements, duckdb_binary):
        inserted["statements"] = statements
        inserted["binary"] = duckdb_binary

    monkeypatch.setattr(run_audit, "detect_relation_type", fake_detect_relation_type)
    monkeypatch.setattr(run_audit, "query_scalar", fake_query_scalar)
    monkeypatch.setattr(run_audit, "run_duckdb", fake_run_duckdb)

    result = run_audit.main()
    captured = capsys.readouterr()
    assert result == 0
    assert "Audit complete" in captured.out
    assert any("INSERT INTO ducklake.audit.table_health" in stmt for stmt in inserted["statements"])


def test_run_audit_handles_missing_relations(monkeypatch, capsys):
    env = DummyEnv()
    monkeypatch.setattr(run_audit, "build_env_config", lambda: env)
    monkeypatch.setattr(run_audit, "ensure_duckdb_binary", lambda _: "duckdb")
    monkeypatch.setattr(run_audit, "detect_relation_type", lambda **_: None)

    result = run_audit.main()
    captured = capsys.readouterr()
    assert result == 1
    assert "No DuckLake relations found" in captured.err
