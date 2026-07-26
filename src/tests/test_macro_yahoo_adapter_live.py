"""Live-network tests for the Yahoo macro adapter -- hits the real
yfinance API (no mock), consistent with how every other external call in
this project is verified. No database needed, but marked ``integration``
anyway (excluded from the default fast unit run).
"""
from __future__ import annotations

import datetime as dt

import pytest

from src.data_sources.base import ValidationStatus
from src.data_sources.macro.taxonomy import SERIES_CATALOG
from src.data_sources.macro.yahoo_finance import YahooFinanceMacroAdapter

pytestmark = pytest.mark.integration


def test_supported_series_is_subset_of_taxonomy():
    # Not equality -- SERIES_CATALOG also has BPS-only series (bps.py)
    # this adapter never claims to serve.
    adapter = YahooFinanceMacroAdapter()
    assert set(adapter.supported_series()) <= set(SERIES_CATALOG)


def test_get_series_returns_real_recent_data_for_every_known_series():
    adapter = YahooFinanceMacroAdapter()
    end = dt.datetime.now(dt.UTC).date()
    start = end - dt.timedelta(days=30)
    for series_code in adapter.supported_series():
        result = adapter.get_series(series_code, start, end)
        assert result.validation_status == ValidationStatus.VALID
        assert result.value  # real points, not empty
        assert all(isinstance(p.value, float) for p in result.value)
        assert all(start <= p.observation_date <= end for p in result.value)


def test_ihsg_composite_is_a_plausible_index_level():
    # Sanity check against known reality, not just "a number came back" --
    # IHSG has been in the thousands for years; a bug that returned e.g. a
    # raw fraction or a wildly wrong series would show up here.
    adapter = YahooFinanceMacroAdapter()
    end = dt.datetime.now(dt.UTC).date()
    result = adapter.get_series("ihsg_composite", end - dt.timedelta(days=10), end)
    assert result.value
    assert 1000 < result.value[-1].value < 20000


def test_unsupported_series_code_raises():
    adapter = YahooFinanceMacroAdapter()
    with pytest.raises(ValueError):
        adapter.get_series("not_a_real_series", dt.date(2026, 1, 1), dt.date(2026, 1, 2))
