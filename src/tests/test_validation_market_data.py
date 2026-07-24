"""Unit tests for OHLCV validation."""
from __future__ import annotations

import datetime as dt

from src.data_sources.market.base import OHLCVBar
from src.validation.market_data import validate_ohlcv_bar

TODAY = dt.date(2026, 7, 24)


def _bar(**overrides):
    defaults = {"trade_date": TODAY, "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0, "volume": 1000}
    defaults.update(overrides)
    return OHLCVBar(**defaults)


def test_valid_bar_passes():
    result = validate_ohlcv_bar(_bar(), today=TODAY)
    assert result.is_valid
    assert result.errors == []


def test_bar_with_none_close_is_not_invalid():
    # Today's still-forming bar -- a freshness concern, not a validation failure.
    result = validate_ohlcv_bar(_bar(close=None), today=TODAY)
    assert result.is_valid


def test_high_less_than_open_fails():
    result = validate_ohlcv_bar(_bar(high=90.0), today=TODAY)
    assert not result.is_valid
    assert any("high" in e for e in result.errors)


def test_low_greater_than_close_fails():
    result = validate_ohlcv_bar(_bar(low=110.0), today=TODAY)
    assert not result.is_valid


def test_negative_price_fails():
    result = validate_ohlcv_bar(_bar(open=-1.0), today=TODAY)
    assert not result.is_valid
    assert any("open" in e for e in result.errors)


def test_zero_price_fails():
    result = validate_ohlcv_bar(_bar(close=0.0), today=TODAY)
    assert not result.is_valid


def test_negative_volume_fails():
    result = validate_ohlcv_bar(_bar(volume=-100), today=TODAY)
    assert not result.is_valid


def test_future_date_fails():
    result = validate_ohlcv_bar(_bar(trade_date=TODAY + dt.timedelta(days=1)), today=TODAY)
    assert not result.is_valid
    assert any("future" in e for e in result.errors)


def test_multiple_errors_all_reported():
    result = validate_ohlcv_bar(_bar(open=-1.0, volume=-5), today=TODAY)
    assert not result.is_valid
    assert len(result.errors) >= 2
