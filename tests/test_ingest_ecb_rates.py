from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from scripts.ingest_ecb_rates import (
    RateRecord,
    build_values_sql,
    parse_ecb_xml,
    select_rate_batch,
)
from scripts.lib.ducklake_ingest import IngestError


SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <gesmes:subject>Reference rates</gesmes:subject>
  <Cube>
    <Cube time="2024-01-01">
      <Cube currency="USD" rate="1.1045"/>
      <Cube currency="GBP" rate="0.8654"/>
    </Cube>
    <Cube time="2024-01-02">
      <Cube currency="USD" rate="1.1133"/>
      <Cube currency="JPY" rate="156.42"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""


def test_parse_ecb_xml_returns_expected_dates():
    observations = parse_ecb_xml(SAMPLE_XML)
    assert set(observations.keys()) == {
        dt.date(2024, 1, 1),
        dt.date(2024, 1, 2),
    }

    jan_first = observations[dt.date(2024, 1, 1)]
    codes = {row.currency_code for row in jan_first}
    # Includes provided currencies plus EUR base.
    assert codes == {"USD", "GBP", "EUR"}
    usd = next(row for row in jan_first if row.currency_code == "USD")
    assert usd.fx_rate == Decimal("1.1045")
    assert usd.currency_name == "US Dollar"


def test_select_rate_batch_with_specific_date():
    observations = parse_ecb_xml(SAMPLE_XML)
    selected_date, rows = select_rate_batch(observations, dt.date(2024, 1, 1))
    assert selected_date == dt.date(2024, 1, 1)
    assert len(rows) == 3  # USD, GBP, EUR


def test_select_rate_batch_defaults_to_latest():
    observations = parse_ecb_xml(SAMPLE_XML)
    selected_date, rows = select_rate_batch(observations, None)
    assert selected_date == dt.date(2024, 1, 2)
    assert any(row.currency_code == "JPY" for row in rows)


def test_select_rate_batch_raises_for_missing_date():
    observations = parse_ecb_xml(SAMPLE_XML)
    with pytest.raises(IngestError):
        select_rate_batch(observations, dt.date(2023, 12, 31))


def test_build_values_sql_formats_rows():
    rows = [
        RateRecord(
            rate_date=dt.date(2024, 1, 1),
            currency_code="USD",
            currency_name="US Dollar",
            fx_rate=Decimal("1.1045"),
        )
    ]
    sql = build_values_sql(rows)
    assert "DATE '2024-01-01'" in sql
    assert "'US Dollar'" in sql
    assert "1.1045" in sql
