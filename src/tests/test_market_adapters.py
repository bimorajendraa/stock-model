"""Tests for the Twelve Data and Sectors.app market adapters.

All HTTP calls are mocked with respx using response shapes taken directly
from each provider's live/documented API (see the adapter modules'
docstrings for how those shapes were verified) -- no live network calls in
the test suite (spec §29: use fixtures/recorded responses, not production
calls).
"""
from __future__ import annotations

import datetime as dt

import httpx
import pytest
import respx

from src.data_sources.base import ProviderUnavailableError
from src.data_sources.market.sectors_app import SectorsAppMarketProvider
from src.data_sources.market.twelve_data import TwelveDataMarketProvider

# --- Twelve Data ---------------------------------------------------------

@respx.mock
def test_twelve_data_list_active_tickers():
    respx.get("https://api.twelvedata.com/stocks", params={"exchange": "IDX"}).mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"symbol": "BBCA", "name": "Bank Central Asia"}, {"symbol": "TLKM", "name": "Telkom"}]},
        )
    )
    provider = TwelveDataMarketProvider(api_key="demo")
    result = provider.list_active_tickers()
    assert result.is_usable()
    assert result.value == ["BBCA", "TLKM"]


@respx.mock
def test_twelve_data_list_companies():
    respx.get("https://api.twelvedata.com/stocks", params={"exchange": "IDX"}).mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"symbol": "BBCA", "name": "Bank Central Asia"}, {"symbol": "TLKM", "name": "Telkom"}]},
        )
    )
    provider = TwelveDataMarketProvider(api_key="demo")
    result = provider.list_companies()
    assert result.is_usable()
    assert [(c.ticker, c.company_name) for c in result.value] == [("BBCA", "Bank Central Asia"), ("TLKM", "Telkom")]


@respx.mock
def test_twelve_data_get_ohlcv_sorts_and_parses():
    respx.get("https://api.twelvedata.com/time_series").mock(
        return_value=httpx.Response(
            200,
            json={
                "meta": {"symbol": "BBCA", "interval": "1day"},
                "values": [
                    {"datetime": "2026-07-02", "open": "9000", "high": "9050", "low": "8950", "close": "9010", "volume": "1000"},
                    {"datetime": "2026-07-01", "open": "8900", "high": "9000", "low": "8880", "close": "8975", "volume": "2000"},
                ],
                "status": "ok",
            },
        )
    )
    provider = TwelveDataMarketProvider(api_key="demo")
    result = provider.get_ohlcv("BBCA", dt.date(2026, 7, 1), dt.date(2026, 7, 2))
    assert result.is_usable()
    assert [b.trade_date for b in result.value] == [dt.date(2026, 7, 1), dt.date(2026, 7, 2)]
    assert result.value[0].close == 8975.0
    assert result.value[0].volume == 2000


@respx.mock
def test_twelve_data_error_status_raises_provider_unavailable():
    respx.get("https://api.twelvedata.com/time_series").mock(
        return_value=httpx.Response(200, json={"code": 401, "message": "bad key", "status": "error"})
    )
    provider = TwelveDataMarketProvider(api_key="bad")
    with pytest.raises(ProviderUnavailableError):
        provider.get_ohlcv("BBCA", dt.date(2026, 7, 1), dt.date(2026, 7, 2))


@respx.mock
def test_twelve_data_rate_limit_raises_provider_unavailable():
    respx.get("https://api.twelvedata.com/stocks").mock(return_value=httpx.Response(429))
    provider = TwelveDataMarketProvider(api_key="demo")
    with pytest.raises(ProviderUnavailableError):
        provider.list_active_tickers()


def test_twelve_data_corporate_actions_not_implemented():
    provider = TwelveDataMarketProvider(api_key="demo")
    with pytest.raises(NotImplementedError):
        provider.get_corporate_actions("BBCA", dt.date(2026, 1, 1), dt.date(2026, 7, 1))


# --- Sectors.app -----------------------------------------------------------

def test_sectors_app_without_api_key_raises_immediately():
    provider = SectorsAppMarketProvider(api_key=None)
    with pytest.raises(ProviderUnavailableError):
        provider.list_active_tickers()


@respx.mock
def test_sectors_app_list_active_tickers_paginates():
    respx.get("https://api.sectors.app/v2/companies/", params={"limit": 200, "offset": 0}).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [{"symbol": "BBCA.JK", "company_name": "Bank Central Asia"}],
                "pagination": {"has_next": True, "next_offset": 200},
            },
        )
    )
    respx.get("https://api.sectors.app/v2/companies/", params={"limit": 200, "offset": 200}).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [{"symbol": "TLKM.JK", "company_name": "Telkom"}],
                "pagination": {"has_next": False, "next_offset": None},
            },
        )
    )
    provider = SectorsAppMarketProvider(api_key="test-key")
    result = provider.list_active_tickers()
    assert result.is_usable()
    assert result.value == ["BBCA", "TLKM"]


@respx.mock
def test_sectors_app_list_companies():
    respx.get("https://api.sectors.app/v2/companies/", params={"limit": 200, "offset": 0}).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [{"symbol": "BBCA.JK", "company_name": "PT Bank Central Asia Tbk."}],
                "pagination": {"has_next": False, "next_offset": None},
            },
        )
    )
    provider = SectorsAppMarketProvider(api_key="test-key")
    result = provider.list_companies()
    assert result.is_usable()
    assert result.value[0].ticker == "BBCA"
    assert result.value[0].company_name == "PT Bank Central Asia Tbk."


@respx.mock
def test_sectors_app_get_ohlcv_only_close_and_volume():
    respx.get("https://api.sectors.app/v2/daily/BBCA/").mock(
        return_value=httpx.Response(
            200,
            json=[{"symbol": "BBCA.JK", "date": "2026-07-02", "close": 8975, "volume": 92219000, "market_cap": 1095329638012500}],
        )
    )
    provider = SectorsAppMarketProvider(api_key="test-key")
    result = provider.get_ohlcv("BBCA", dt.date(2026, 7, 2), dt.date(2026, 7, 2))
    assert result.is_usable()
    bar = result.value[0]
    assert bar.close == 8975
    assert bar.open is None and bar.high is None and bar.low is None


@respx.mock
def test_sectors_app_get_ohlcv_paginates_beyond_90_days():
    route = respx.get("https://api.sectors.app/v2/daily/BBCA/")
    route.mock(return_value=httpx.Response(200, json=[]))
    provider = SectorsAppMarketProvider(api_key="test-key")
    provider.get_ohlcv("BBCA", dt.date(2026, 1, 1), dt.date(2026, 6, 1))  # ~150 days
    assert route.call_count >= 2


@respx.mock
def test_sectors_app_corporate_actions_filters_by_date_and_flattens():
    respx.get("https://api.sectors.app/v2/company/corporate-actions/BBCA/").mock(
        return_value=httpx.Response(
            200,
            json={
                "symbol": "BBCA.JK",
                "corporate_actions": {
                    "agm": [{"agm_date": "2025-03-12"}],
                    "bonus": None,
                    "warrant": None,
                    "dividend": [
                        {"ex_date": "2025-12-03", "payment_date": "2025-12-22", "dividend_amount": 55},
                        {"ex_date": "2020-01-01", "payment_date": "2020-01-15", "dividend_amount": 10},
                    ],
                    "right_issue": None,
                    "stock_split": [{"date": "2021-10-13", "split_ratio": 5}],
                    "upcoming_dividend": None,
                },
            },
        )
    )
    provider = SectorsAppMarketProvider(api_key="test-key")
    result = provider.get_corporate_actions("BBCA", dt.date(2025, 1, 1), dt.date(2025, 12, 31))
    types = {a["action_type"] for a in result.value}
    assert types == {"dividend"}  # stock_split (2021) and old dividend (2020) fall outside the range
    assert result.value[0]["dividend_amount"] == 55
