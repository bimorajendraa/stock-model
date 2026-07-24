"""Unit tests for MarketDataProviderSelector -- the production guardrail
in particular (spec section 15: research-only providers must never be
used when MARKET_DATA_USAGE_MODE=production)."""
from __future__ import annotations

import httpx
import pytest
import respx

from src.data_sources.market.capability import ProviderAccessError
from src.data_sources.market.selector import (
    MarketDataProviderSelector,
    NoLicensedProviderAvailableError,
)
from src.data_sources.market.twelve_data import TwelveDataMarketProvider
from src.data_sources.market.yahoo_finance import YahooFinanceOHLCVAdapter


def _selector(configured="auto", usage_mode="research", enable_yahoo=True, api_key="demo"):
    return MarketDataProviderSelector(
        twelve_data_provider=TwelveDataMarketProvider(api_key=api_key),
        yahoo_provider=YahooFinanceOHLCVAdapter(),
        twelve_data_api_key=api_key,
        configured_provider=configured,
        usage_mode=usage_mode,
        enable_yahoo_fallback=enable_yahoo,
    )


@respx.mock
def test_auto_falls_back_to_yahoo_in_research_mode_when_twelve_data_unavailable():
    respx.get("https://api.twelvedata.com/time_series").mock(
        return_value=httpx.Response(200, json={"code": 401, "message": "invalid apikey"})
    )
    selector = _selector(usage_mode="research")
    provider, capability = selector.select("BBCA")
    assert provider.provider_name == "yahoo_finance"
    assert capability.usage_mode == "research"
    assert capability.supports_commercial_use is False


@respx.mock
def test_auto_refuses_to_select_anything_in_production_mode_when_twelve_data_unavailable():
    respx.get("https://api.twelvedata.com/time_series").mock(
        return_value=httpx.Response(200, json={"code": 401, "message": "invalid apikey"})
    )
    selector = _selector(usage_mode="production")
    with pytest.raises(NoLicensedProviderAvailableError):
        selector.select("BBCA")


def test_forcing_yahoo_finance_in_production_mode_raises():
    selector = _selector(configured="yahoo_finance", usage_mode="production")
    with pytest.raises(NoLicensedProviderAvailableError):
        selector.select("BBCA")


def test_forcing_yahoo_finance_in_research_mode_works():
    selector = _selector(configured="yahoo_finance", usage_mode="research")
    provider, capability = selector.select("BBCA")
    assert provider.provider_name == "yahoo_finance"
    assert capability.status == "available"


@respx.mock
def test_auto_raises_when_fallback_disabled_and_twelve_data_unavailable():
    respx.get("https://api.twelvedata.com/time_series").mock(
        return_value=httpx.Response(200, json={"code": 401, "message": "invalid apikey"})
    )
    selector = _selector(usage_mode="research", enable_yahoo=False)
    with pytest.raises(ProviderAccessError):
        selector.select("BBCA")


@respx.mock
def test_forcing_twelve_data_when_unavailable_raises():
    respx.get("https://api.twelvedata.com/time_series").mock(
        return_value=httpx.Response(200, json={"code": 401, "message": "invalid apikey"})
    )
    selector = _selector(configured="twelve_data")
    with pytest.raises(ProviderAccessError):
        selector.select("BBCA")


def test_unknown_configured_provider_raises_value_error():
    selector = _selector(configured="not_a_real_provider")
    with pytest.raises(ValueError):
        selector.select("BBCA")
