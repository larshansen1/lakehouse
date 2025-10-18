from __future__ import annotations

import datetime as dt

import pytest

from scripts.lib import load_utils
from scripts.lib.ducklake_ingest import IngestError


def test_sanitize_for_path_handles_symbols():
    assert load_utils.sanitize_for_path(" demo::batch ") == "demo-batch"


def test_parse_load_date_rejects_invalid():
    with pytest.raises(IngestError):
        load_utils.parse_load_date("2024-13-01")


def test_resolve_batch_id_uses_default(monkeypatch):
    fixed = dt.datetime(2024, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc)
    monkeypatch.setattr(load_utils, "_utc_now", lambda: fixed)
    assert load_utils.resolve_batch_id(None) == "2024-01-01T12:00:00Z"


def test_normalize_business_keys_merges_lists():
    result = load_utils.normalize_business_keys(["id", "user_id,name"], default="id")
    assert result == ["id", "user_id", "name"]


def test_ensure_valid_identifier_rejects_bad_names():
    with pytest.raises(IngestError):
        load_utils.ensure_valid_identifier("invalid column")


def test_query_scalar_with_retry_eventually_succeeds(monkeypatch):
    attempts = []

    def fake_query(sql, **kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise IngestError("transient http failure")
        return 42

    monkeypatch.setattr(load_utils, "query_scalar", fake_query)
    monkeypatch.setattr(load_utils.time, "sleep", lambda *_: None)

    result = load_utils.query_scalar_with_retry(
        "SELECT 1",
        duckdb_binary="duckdb",
        env_config=object(),
        attempts=3,
        delay_seconds=0,
    )
    assert result == 42
    assert len(attempts) == 3


def test_run_duckdb_with_retry_raises_after_attempts(monkeypatch):
    attempts = []

    def fake_run(statements, duckdb_binary, **kwargs):
        attempts.append(1)
        raise IngestError("HTTP timeout")

    monkeypatch.setattr(load_utils, "run_duckdb", fake_run)
    monkeypatch.setattr(load_utils.time, "sleep", lambda *_: None)

    with pytest.raises(IngestError):
        load_utils.run_duckdb_with_retry(["SELECT 1"], duckdb_binary="duckdb", attempts=2, delay_seconds=0)
    assert len(attempts) == 2


def test_append_drop_statement_handles_view_and_table():
    statements: list[str] = []
    load_utils.append_drop_statement(statements, schema="bronze", name="v", relation_type="VIEW")
    load_utils.append_drop_statement(statements, schema="bronze", name="t", relation_type="TABLE")
    assert statements == [
        "DROP VIEW IF EXISTS ducklake.bronze.v",
        "DROP TABLE IF EXISTS ducklake.bronze.t",
    ]
