"""Deterministic tests for the authorized IDX XBRL archive adapter."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from src.data_sources.base import ProviderUnavailableError, ValidationStatus
from src.data_sources.fundamentals.idx_xbrl import IDXOfficialXBRLArchiveAdapter

_XBRL = """<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
             xmlns:id="http://example.com/idx-taxonomy">
  <xbrli:context id="FY2025">
    <xbrli:entity><xbrli:identifier scheme="IDX">BBCA</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period>
  </xbrli:context>
  <id:Assets contextRef="FY2025" decimals="0">1000000</id:Assets>
  <id:ProfitLoss contextRef="FY2025" decimals="0">125000</id:ProfitLoss>
  <id:RasioKPMM contextRef="FY2025" decimals="4">0.2875</id:RasioKPMM>
</xbrli:xbrl>
"""


def _write_archive(tmp_path, *, published_at: str = "2026-01-23T17:42:00+07:00"):
    (tmp_path / "BBCA-2025FY.xbrl").write_text(_XBRL, encoding="utf-8")
    manifest = {
        "account_map": {"RasioKPMM": "capital_adequacy_ratio_reported"},
        "filings": [
            {
                "ticker": "BBCA",
                "fiscal_period": "2025FY",
                "statement_type": "annual",
                "period_end": "2025-12-31",
                "published_at": published_at,
                "xbrl_file": "BBCA-2025FY.xbrl",
                "document_url": "https://www.idx.co.id/official/filing/123",
                "filing_reference": "IDX-123",
                "context_id": "FY2025",
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_idx_xbrl_uses_official_publication_timestamp_and_maps_facts(tmp_path):
    adapter = IDXOfficialXBRLArchiveAdapter(_write_archive(tmp_path))

    listed = adapter.list_available_statements("BBCA", dt.date(2020, 1, 1))
    result = adapter.get_statement("BBCA", "2025FY")

    assert listed.value == ["2025FY"]
    assert result.validation_status == ValidationStatus.VALID
    assert result.available_at == dt.datetime(2026, 1, 23, 10, 42, tzinfo=dt.UTC)
    assert result.value.source_format == "xbrl"
    assert result.value.available_at_basis == "official_idx_publication_timestamp"
    assert result.value.filing_reference == "IDX-123"
    assert result.value.line_items == {
        "total_assets": 1_000_000.0,
        "net_income": 125_000.0,
        "capital_adequacy_ratio_reported": 0.2875,
    }


def test_idx_xbrl_rejects_publication_before_period_end(tmp_path):
    with pytest.raises(ProviderUnavailableError, match="cannot precede"):
        IDXOfficialXBRLArchiveAdapter(_write_archive(tmp_path, published_at="2025-12-01T12:00:00+07:00"))


def test_idx_xbrl_requires_timezone_on_publication_timestamp(tmp_path):
    with pytest.raises(ValueError, match="timezone"):
        IDXOfficialXBRLArchiveAdapter(_write_archive(tmp_path, published_at="2026-01-23T17:42:00"))
