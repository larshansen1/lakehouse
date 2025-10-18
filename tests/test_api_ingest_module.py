from __future__ import annotations

from scripts.lib import api_ingest


def test_parse_args_defaults():
    args = api_ingest.parse_args([])
    assert args.dataset == api_ingest.DEFAULT_DATASET
    assert args.sample_size == api_ingest.DEFAULT_SAMPLE_SIZE


def test_parse_args_collects_business_keys():
    args = api_ingest.parse_args([
        "--business-key",
        "userId",
        "--business-key",
        "id,name",
    ])
    assert args.business_keys == ["userId", "id,name"]
