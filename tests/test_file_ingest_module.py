from __future__ import annotations

from pathlib import Path

import pytest

from scripts.lib.file_ingest import determine_reader_expression
from scripts.lib.ducklake_ingest import IngestError


def test_determine_reader_expression_csv(tmp_path: Path):
    csv_file = tmp_path / "sample.csv"
    csv_file.write_text("id,name\n1,foo\n", encoding="utf-8")
    expr = determine_reader_expression(csv_file)
    assert "read_csv_auto" in expr


def test_determine_reader_expression_parquet(tmp_path: Path):
    parquet_file = tmp_path / "sample.parquet"
    parquet_file.write_bytes(b"")
    expr = determine_reader_expression(parquet_file)
    assert "read_parquet" in expr


def test_determine_reader_expression_rejects_unknown(tmp_path: Path):
    unknown = tmp_path / "sample.txt"
    unknown.write_text("hello", encoding="utf-8")
    with pytest.raises(IngestError):
        determine_reader_expression(unknown)
