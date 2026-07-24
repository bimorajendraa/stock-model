"""Yahoo Finance adapter via ``yfinance`` -- RESEARCH/DEV FALLBACK ONLY.

Verified live against the real API on 2026-07-24/25 (BBCA.JK): returns real
OHLCV with Asia/Jakarta-tz-aware dates, real dividends (one entry --
2025-12-03, amount 55 -- independently matches the example in Sectors.app's
live OpenAPI schema, a useful cross-check), and real splits.

**This is explicitly NOT an official IDX data source** (spec's own
constraint: never claim unofficial data is official). ``yfinance`` scrapes
an undocumented Yahoo endpoint outside Yahoo's ToS-sanctioned API -- legally
gray, which is why every record sourced from here is tagged
``usage_restriction=research_only`` and this adapter is refused outright
when ``MARKET_DATA_USAGE_MODE=production`` (see
``src/data_sources/market/selector.py``). Never promote this to a
production/commercial data path without a proper licensing review.

Ticker mapping: IDX ticker -> Yahoo symbol is `f"{ticker}.JK"` by default.
The company's canonical ticker in ``companies.ticker`` is never touched --
provider-specific symbol mapping is a purely adapter-local concern (and can
be overridden per-company via ``company_provider_symbols`` at the ingestion
layer, for the rare case the suffix rule doesn't hold).
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Callable

import yfinance as yf

from src.data_sources.base import (
    AccessType,
    ProviderUnavailableError,
    SourceDescriptor,
    SourcedValue,
    ValidationStatus,
)
from src.data_sources.market.base import CompanyRecord, MarketDataProvider, OHLCVBar

_SOURCE = SourceDescriptor(
    name="yahoo_finance",
    url="https://finance.yahoo.com",
    access_type=AccessType.FALLBACK_PROVIDER,
)


def default_yahoo_symbol(ticker: str) -> str:
    return f"{ticker}.JK"


class YahooFinanceOHLCVAdapter(MarketDataProvider):
    def __init__(self, symbol_resolver: Callable[[str], str] | None = None) -> None:
        self._symbol_resolver = symbol_resolver or default_yahoo_symbol

    @property
    def provider_name(self) -> str:
        return "yahoo_finance"

    def list_active_tickers(self) -> SourcedValue[list[str]]:
        raise NotImplementedError(
            "yahoo_finance is not used as a company directory -- Twelve Data already "
            "fills that role (verified working). Yahoo Finance is OHLCV/corporate-actions only."
        )

    def list_companies(self) -> SourcedValue[list[CompanyRecord]]:
        raise NotImplementedError(
            "yahoo_finance is not used as a company directory -- see list_active_tickers."
        )

    def get_ohlcv(self, ticker: str, start: dt.date, end: dt.date) -> SourcedValue[list[OHLCVBar]]:
        now = dt.datetime.now(dt.UTC)
        symbol = self._symbol_resolver(ticker)
        try:
            history = yf.Ticker(symbol).history(
                start=start.isoformat(),
                end=(end + dt.timedelta(days=1)).isoformat(),  # yfinance end is exclusive
                auto_adjust=False,
                actions=True,
                raise_errors=False,
            )
        except Exception as exc:  # yfinance raises assorted requests/HTTP exceptions
            raise ProviderUnavailableError(f"yahoo_finance request failed for {symbol}: {exc}") from exc

        bars = [
            OHLCVBar(
                trade_date=index.date(),
                open=_clean(row.get("Open")),
                high=_clean(row.get("High")),
                low=_clean(row.get("Low")),
                close=_clean(row.get("Close")),
                volume=_clean_int(row.get("Volume")),
                adjusted_close=_clean(row.get("Adj Close")),
                provider_adjustment_status="provider_split_and_dividend_adjusted",
            )
            for index, row in history.iterrows()
        ]
        bars.sort(key=lambda b: b.trade_date)
        return SourcedValue(
            value=bars,
            source=_SOURCE,
            retrieved_at=now,
            available_at=now,
            period_start=start,
            period_end=end,
            validation_status=ValidationStatus.VALID if bars else ValidationStatus.INSUFFICIENT,
        )

    def get_corporate_actions(self, ticker: str, start: dt.date, end: dt.date) -> SourcedValue[list[dict]]:
        now = dt.datetime.now(dt.UTC)
        symbol = self._symbol_resolver(ticker)
        try:
            yf_ticker = yf.Ticker(symbol)
            dividends = yf_ticker.dividends
            splits = yf_ticker.splits
        except Exception as exc:
            raise ProviderUnavailableError(f"yahoo_finance request failed for {symbol}: {exc}") from exc

        actions: list[dict] = []
        for ex_date, amount in dividends.items():
            d = ex_date.date()
            if start <= d <= end:
                actions.append(
                    {
                        "action_type": "cash_dividend",
                        "ex_date": d.isoformat(),
                        "cash_amount": float(amount),
                        "verification_status": "provider_reported",
                    }
                )
        for ex_date, ratio in splits.items():
            d = ex_date.date()
            if start <= d <= end:
                ratio = float(ratio)
                if ratio >= 1:
                    action_type, split_from, split_to = "stock_split", 1, ratio
                else:
                    action_type, split_from, split_to = "reverse_split", round(1 / ratio, 4), 1
                actions.append(
                    {
                        "action_type": action_type,
                        "ex_date": d.isoformat(),
                        "split_from": split_from,
                        "split_to": split_to,
                        "verification_status": "provider_reported",
                    }
                )

        return SourcedValue(
            value=actions,
            source=_SOURCE,
            retrieved_at=now,
            available_at=now,
            period_start=start,
            period_end=end,
            validation_status=ValidationStatus.VALID,
        )


def _clean(value) -> float | None:
    if value is None:
        return None
    try:
        import math

        f = float(value)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _clean_int(value) -> int | None:
    f = _clean(value)
    return None if f is None else int(f)
