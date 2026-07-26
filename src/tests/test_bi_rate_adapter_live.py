"""Live test against the real bi.go.id pages (real network, real ASP.NET
postback pagination) -- same "verify against the real thing" discipline
as every other ``_live`` test file in this project. Excluded from CI
(``--ignore-glob='**/*_live.py'``), for local/manual verification.
"""
from __future__ import annotations

import datetime as dt

import pytest

from src.data_sources.base import ValidationStatus
from src.data_sources.macro.bi_rate import BankIndonesiaJISDORAdapter, BankIndonesiaRateHTMLAdapter

pytestmark = pytest.mark.integration


def test_bi_rate_returns_real_recent_decisions():
    adapter = BankIndonesiaRateHTMLAdapter()
    result = adapter.get_series("bi_rate", dt.date(2020, 1, 1), dt.date(2026, 12, 31))
    assert result.validation_status == ValidationStatus.VALID
    assert len(result.value) >= 10  # at least 1 page's worth
    for point in result.value:
        assert 0 < point.value < 20  # a real BI-Rate is a small single-digit-to-low-double-digit percentage
        assert point.available_at.date() == point.observation_date


def test_jisdor_returns_real_recent_rates():
    adapter = BankIndonesiaJISDORAdapter()
    result = adapter.get_series("usdidr_jisdor", dt.date(2026, 1, 1), dt.date(2026, 12, 31))
    assert result.validation_status == ValidationStatus.VALID
    assert len(result.value) >= 5
    for point in result.value:
        assert 10000 < point.value < 25000  # a real USD/IDR rate is in this real order of magnitude
