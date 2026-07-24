"""Provider adapter contract tests.

These use a minimal fixture implementation of each interface -- not a real
provider -- purely to prove the abstraction is implementable and that
SourcedValue's provenance/usability logic behaves as intended. Real
adapters (Tahap 2) get their own tests against recorded fixtures, not fake
production data (spec §29).
"""
from __future__ import annotations

import datetime as dt

import pytest

from src.data_sources.base import (
    AccessType,
    SourceDescriptor,
    SourcedValue,
    ValidationStatus,
)
from src.data_sources.market.base import CompanyRecord, MarketDataProvider, OHLCVBar


class _FixtureMarketProvider(MarketDataProvider):
    @property
    def provider_name(self) -> str:
        return "fixture-market"

    def list_active_tickers(self) -> SourcedValue[list[str]]:
        return _wrap(["BBCA", "TLKM"])

    def list_companies(self) -> SourcedValue[list[CompanyRecord]]:
        return _wrap([CompanyRecord("BBCA", "Bank Central Asia"), CompanyRecord("TLKM", "Telkom Indonesia")])

    def get_ohlcv(self, ticker, start, end) -> SourcedValue[list[OHLCVBar]]:
        bars = [OHLCVBar(trade_date=start, open=100, high=101, low=99, close=100, volume=1000)]
        return _wrap(bars)

    def get_corporate_actions(self, ticker, start, end) -> SourcedValue[list[dict]]:
        return _wrap([])


def _wrap(value):
    return SourcedValue(
        value=value,
        source=SourceDescriptor(name="fixture", url="https://example.invalid", access_type=AccessType.DOCUMENTED_FREE),
        retrieved_at=dt.datetime(2026, 7, 24, tzinfo=dt.UTC),
        available_at=dt.datetime(2026, 7, 24, tzinfo=dt.UTC),
        period_start=None,
        period_end=None,
        validation_status=ValidationStatus.VALID,
    )


def test_market_provider_is_abstract():
    with pytest.raises(TypeError):
        MarketDataProvider()  # type: ignore[abstract]


def test_fixture_market_provider_satisfies_contract():
    provider = _FixtureMarketProvider()
    tickers = provider.list_active_tickers()
    assert tickers.is_usable()
    assert "BBCA" in tickers.value

    bars = provider.get_ohlcv("BBCA", dt.date(2026, 7, 1), dt.date(2026, 7, 24))
    assert bars.is_usable()
    assert bars.value[0].close == 100


def test_sourced_value_insufficient_is_not_usable():
    sv = SourcedValue(
        value=None,
        source=SourceDescriptor(name="fixture", url="https://example.invalid", access_type=AccessType.FALLBACK_PROVIDER),
        retrieved_at=dt.datetime(2026, 7, 24, tzinfo=dt.UTC),
        available_at=dt.datetime(2026, 7, 24, tzinfo=dt.UTC),
        period_start=None,
        period_end=None,
        validation_status=ValidationStatus.INSUFFICIENT,
    )
    assert not sv.is_usable()


def test_sourced_value_invalid_status_is_not_usable_even_with_value():
    sv = SourcedValue(
        value=123,
        source=SourceDescriptor(name="fixture", url="https://example.invalid", access_type=AccessType.OFFICIAL),
        retrieved_at=dt.datetime(2026, 7, 24, tzinfo=dt.UTC),
        available_at=dt.datetime(2026, 7, 24, tzinfo=dt.UTC),
        period_start=None,
        period_end=None,
        validation_status=ValidationStatus.INVALID,
    )
    assert not sv.is_usable()
