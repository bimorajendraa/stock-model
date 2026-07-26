"""Yahoo Finance adapter for macro/market-wide series -- RESEARCH/DEV
FALLBACK ONLY, same status as the market/fundamentals Yahoo adapters.

**What was actually investigated (2026-07-25), live, before writing any
code** (spec section 2.2: never a fabricated/guessed source):

- **BPS (Statistik Indonesia) Web API** (`webapi.bps.go.id`) -- real,
  documented, and does cover inflation/CPI, but requires a registered API
  key token (`https://webapi.bps.go.id/documentation/`) this project does
  not have. Per this project's standing rule (never ask for a new
  provider credential unless a real, verified need is established first,
  and even then only with the user's go-ahead), this is a known,
  documented gap -- not silently worked around.
- **Bank Indonesia's own site** (`bi.go.id`) -- BI-Rate/7-Day Reverse Repo
  Rate is published there, but checked live and found to be HTML-only
  (a press-release table), no JSON/API/RSS endpoint. Scraping that HTML
  page would be exactly the kind of programmatic-access-outside-intended-
  use case spec section 2.5-6 is cautious about (same category of
  reasoning that excluded Stooq's JS-gated CSV download in
  `docs/data_sources.md`) -- excluded, not worked around.
- **yfinance** -- already trusted (research_only) for OHLCV/fundamentals
  -- also has real, live, keyless data for FX and index/commodity
  tickers: `USDIDR=X` (USD/IDR spot), `^JKSE` (IDX Composite/IHSG),
  `^TNX` (US 10-Year Treasury yield), `CL=F` (WTI crude). Verified live:
  all four return real, current, plausible values (IHSG ~6,196 points,
  USD/IDR ~17,935, US 10Y ~4.68%, WTI ~$89/bbl as of 2026-07-24/25).
  Guessed tickers for an Indonesian government bond yield and Brent crude
  (`ID10YT.B`, `BRENTOIL=F`) both correctly 404'd -- not silently
  substituted with something else.

**Known, honestly-stated limitation**: `us_10y_treasury_yield` is a
**global/US** rate-environment proxy, not Indonesia's own risk-free rate
or BI-Rate. It does NOT resolve the "no real discount-rate input for DCF"
gap noted in `docs/valuation.md` -- that specifically needs an
Indonesia-domestic rate, which this adapter does not provide. Do not
treat this series as a BI-Rate substitute anywhere downstream.

**Real bug found and fixed (2026-07-25, same day BPS was added)**: this
adapter fetches years of backfill in one call but originally only
returned a single batch-level `available_at=now` with no per-point
value -- meaning `ingest_macro_series` stamped *every* historical point,
including one from 2016, as only having become available *today*. Not
caught until building `bps.py`, whose per-point `available_at` made the
gap in this file obvious by contrast. Fixed here with a same-day-close
estimate (`observation_date + 1 day`) per point -- daily market/FX/index
data is realistically public same day (T+0/T+1), unlike a financial
statement's weeks-to-months lag, so this doesn't need BPS-style
month-plus-lag logic, just per-point dates instead of one shared "now".
"""
from __future__ import annotations

import datetime as dt
import math

import yfinance as yf

from src.data_sources.base import (
    AccessType,
    ProviderUnavailableError,
    SourceDescriptor,
    SourcedValue,
    ValidationStatus,
)
from src.data_sources.macro.base import MacroDataProvider, SeriesPoint
from src.data_sources.macro.taxonomy import SERIES_CATALOG

_SOURCE = SourceDescriptor(
    name="yahoo_finance_macro",
    url="https://finance.yahoo.com",
    access_type=AccessType.FALLBACK_PROVIDER,
)

# series_code -> Yahoo-specific symbol. Only this project's Yahoo-field
# mapping lives here; series_name/unit/table routing is the
# provider-agnostic SERIES_CATALOG in taxonomy.py.
_YAHOO_SYMBOLS: dict[str, str] = {
    "usdidr_fx": "USDIDR=X",
    "us_10y_treasury_yield": "^TNX",
    "ihsg_composite": "^JKSE",
    "wti_crude_oil": "CL=F",
}
# subset, not equality -- SERIES_CATALOG also has BPS-served series (bps.py)
assert _YAHOO_SYMBOLS.keys() <= SERIES_CATALOG.keys()


def _clean(value) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


class YahooFinanceMacroAdapter(MacroDataProvider):
    @property
    def provider_name(self) -> str:
        return "yahoo_finance_macro"

    def supported_series(self) -> list[str]:
        return list(_YAHOO_SYMBOLS)

    def get_series(self, series_code: str, start: dt.date, end: dt.date) -> SourcedValue[list[SeriesPoint]]:
        now = dt.datetime.now(dt.UTC)
        if series_code not in _YAHOO_SYMBOLS:
            raise ValueError(f"unsupported series_code: {series_code!r} -- see supported_series()")

        symbol = _YAHOO_SYMBOLS[series_code]
        try:
            history = yf.Ticker(symbol).history(
                start=start.isoformat(),
                end=(end + dt.timedelta(days=1)).isoformat(),  # yfinance end is exclusive
                auto_adjust=False,
                raise_errors=False,
            )
        except Exception as exc:  # yfinance raises assorted transport/parsing exceptions
            raise ProviderUnavailableError(f"yahoo_finance_macro request failed for {symbol}: {exc}") from exc

        points = [
            SeriesPoint(
                observation_date=index.date(),
                value=_clean(row.get("Close")),
                # same-day-close estimate, not the batch fetch time -- see
                # module docstring's "real bug found and fixed" note.
                available_at=dt.datetime.combine(index.date() + dt.timedelta(days=1), dt.time.min, tzinfo=dt.UTC),
            )
            for index, row in history.iterrows()
        ]
        points = [p for p in points if p.value is not None]
        points.sort(key=lambda p: p.observation_date)

        return SourcedValue(
            value=points,
            source=_SOURCE,
            retrieved_at=now,
            available_at=now,
            period_start=start,
            period_end=end,
            validation_status=ValidationStatus.VALID if points else ValidationStatus.INSUFFICIENT,
        )
