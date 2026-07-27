"""Yahoo Finance adapter for financial statements via ``yfinance`` --
RESEARCH/DEV FALLBACK ONLY, same status as ``market/yahoo_finance.py``.

Verified live against real IDX tickers on 2026-07-25: BBCA.JK (bank --
income_stmt/balance_sheet/cashflow all real, financialCurrency=IDR, net
income ~57.5T IDR FY2025 matches the publicly known figure) and TLKM.JK
(non-bank -- has the "standard" Cost Of Revenue/Gross Profit lines a bank
doesn't report, confirming the sector-dependent structure spec section 3.5
warns about). Both annual (``income_stmt`` etc., ~4-5 fiscal years) and
quarterly (``quarterly_income_stmt`` etc., ~5 quarters) are available and
are genuinely discrete-quarter figures, not year-to-date cumulative
(cross-checked: BBCA's four 2025 quarterly net-income figures sum to
approximately its FY2025 annual figure).

**Known, honestly-documented limitation -- read before using available_at
downstream**: yfinance exposes each statement's fiscal ``period_end`` but
*not* the real public-disclosure date. Spec section 3.3 forbids treating
those as the same date (a Q4 statement is not "available" the moment the
quarter ends -- it isn't filed for weeks/months). Since no real filing
date exists from this source, ``available_at`` here is a **conservative
estimate**: ``period_end + 120 days`` for annual statements, ``period_end
+ 60 days`` for quarterly -- both deliberately upper-bound the real BEI/
OJK filing deadlines (POJK 29/2016: annual FS within 120 days of FY-end;
BEI Peraturan I-E: interim reports within 30-60 days of quarter-end).
Erring long is the safe direction for point-in-time correctness --
UNDERestimating available_at is the actual leakage risk (a model "seeing"
a number before it was real-world-public); OVERestimating only means
conservatively under-using very recent data, never leakage. This estimate
is recorded in ``raw_payload`` as ``available_at_basis`` so nothing
downstream mistakes it for a filed date. If a real filing-date source is
ever integrated, this adapter's estimate must be treated as inferior and
replaced, not merged/averaged with it.

Sector-dependent line items (e.g. banks have no ``Cost Of Revenue``/
``Gross Profit``; only some issuers report ``EBITDA``) are simply omitted
from ``line_items`` when not present -- never backfilled with a fabricated
0 or interpolated value (spec section 2.12/6.3).
"""
from __future__ import annotations

import datetime as dt
import math

import pandas as pd
import yfinance as yf

from src.data_sources.base import (
    AccessType,
    ProviderUnavailableError,
    SourceDescriptor,
    SourcedValue,
    ValidationStatus,
)
from src.data_sources.fundamentals.base import FinancialStatementDocument, FundamentalsProvider
from src.data_sources.fundamentals.taxonomy import ACCOUNT_CODE_SECTIONS, CORE_ACCOUNT_CODES
from src.data_sources.market.yahoo_finance import default_yahoo_symbol

_SOURCE = SourceDescriptor(
    name="yahoo_finance_fundamentals",
    url="https://finance.yahoo.com",
    access_type=AccessType.FALLBACK_PROVIDER,
)

_ANNUAL_LAG_DAYS = 120
_QUARTERLY_LAG_DAYS = 60

# account_code -> candidate yfinance row names in priority order (first
# match wins). Section for each code comes from the shared, provider-
# agnostic ACCOUNT_CODE_SECTIONS taxonomy -- this map is only the
# Yahoo-specific field-name lookup. Every item is skipped (not fabricated)
# when a company's statement doesn't report it (e.g. banks have no "Cost
# Of Revenue"/"Gross Profit").
_YAHOO_FIELD_NAMES: dict[str, tuple[str, ...]] = {
    "revenue": ("Total Revenue",),
    "cost_of_revenue": ("Cost Of Revenue",),
    "gross_profit": ("Gross Profit",),
    "operating_income": ("Operating Income",),
    "operating_expense": ("Operating Expense",),
    "net_interest_income": ("Net Interest Income",),
    "interest_income": ("Interest Income",),
    "interest_expense": ("Interest Expense",),
    "ebitda": ("EBITDA",),
    "pretax_income": ("Pretax Income",),
    "tax_expense": ("Tax Provision",),
    "net_income": ("Net Income",),
    "eps_basic": ("Basic EPS",),
    "eps_diluted": ("Diluted EPS",),
    "shares_basic": ("Basic Average Shares",),
    "shares_diluted": ("Diluted Average Shares",),
    "total_assets": ("Total Assets",),
    "total_liabilities": ("Total Liabilities Net Minority Interest",),
    "total_equity": ("Stockholders Equity",),
    "current_assets": ("Current Assets",),
    "current_liabilities": ("Current Liabilities",),
    "total_debt": ("Total Debt",),
    "cash_and_equivalents": ("Cash And Cash Equivalents",),
    "shares_outstanding": ("Ordinary Shares Number",),
    "operating_cash_flow": ("Operating Cash Flow", "Cash Flowsfromusedin Operating Activities Direct"),
    "investing_cash_flow": ("Investing Cash Flow",),
    "financing_cash_flow": ("Financing Cash Flow",),
    "free_cash_flow": ("Free Cash Flow",),
    "capital_expenditure": ("Capital Expenditure",),
    "dividends_paid": ("Cash Dividends Paid",),
}
assert _YAHOO_FIELD_NAMES.keys() == CORE_ACCOUNT_CODES


def _clean(value) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _fiscal_period(period_end: dt.date, statement_type: str) -> str:
    if statement_type == "annual":
        return f"{period_end.year}FY"
    quarter = ((period_end.month - 1) // 3) + 1
    return f"{period_end.year}Q{quarter}"


def _estimated_available_at(period_end: dt.date, statement_type: str) -> dt.datetime:
    lag = _ANNUAL_LAG_DAYS if statement_type == "annual" else _QUARTERLY_LAG_DAYS
    return dt.datetime.combine(period_end + dt.timedelta(days=lag), dt.time.min, tzinfo=dt.UTC)


class YahooFinanceFundamentalsAdapter(FundamentalsProvider):
    def __init__(self, symbol_resolver=None) -> None:
        self._symbol_resolver = symbol_resolver or default_yahoo_symbol
        self._cache: dict[str, dict[str, dict]] = {}

    @property
    def provider_name(self) -> str:
        return "yahoo_finance_fundamentals"

    def _periods(self, ticker: str) -> dict[str, dict]:
        """ticker -> {fiscal_period: {"statement_type", "period_end",
        "line_items"}}, built once per ticker and cached on this instance."""
        if ticker in self._cache:
            return self._cache[ticker]

        symbol = self._symbol_resolver(ticker)
        try:
            yf_ticker = yf.Ticker(symbol)
            statements = {
                ("annual", "income_statement"): yf_ticker.income_stmt,
                ("annual", "balance_sheet"): yf_ticker.balance_sheet,
                ("annual", "cash_flow"): yf_ticker.cashflow,
                ("quarterly", "income_statement"): yf_ticker.quarterly_income_stmt,
                ("quarterly", "balance_sheet"): yf_ticker.quarterly_balance_sheet,
                ("quarterly", "cash_flow"): yf_ticker.quarterly_cashflow,
            }
        except Exception as exc:  # yfinance raises assorted transport/parsing exceptions
            raise ProviderUnavailableError(f"yahoo_finance_fundamentals request failed for {symbol}: {exc}") from exc

        periods: dict[str, dict] = {}
        for (statement_type, section), df in statements.items():
            if df is None or df.empty:
                continue
            for column in df.columns:
                if not isinstance(column, pd.Timestamp):
                    continue
                period_end = column.date()
                # yfinance sometimes returns an extra all-NaN trailing
                # column (older period with no real data yet) -- skip
                # rather than record a hollow statement.
                col_values = df[column]
                if col_values.dropna().empty:
                    continue

                fiscal_period = _fiscal_period(period_end, statement_type)
                entry = periods.setdefault(
                    fiscal_period,
                    {"statement_type": statement_type, "period_end": period_end, "line_items": {}},
                )
                for account_code, candidates in _YAHOO_FIELD_NAMES.items():
                    if ACCOUNT_CODE_SECTIONS[account_code] != section or account_code in entry["line_items"]:
                        continue
                    for candidate in candidates:
                        if candidate in df.index:
                            value = _clean(df.loc[candidate, column])
                            if value is not None:
                                entry["line_items"][account_code] = value
                                break

        self._cache[ticker] = periods
        return periods

    def list_available_statements(self, ticker: str, since: dt.date) -> SourcedValue[list[str]]:
        now = dt.datetime.now(dt.UTC)
        periods = self._periods(ticker)
        available = [
            fp
            for fp, entry in periods.items()
            if entry["line_items"]
            and _estimated_available_at(entry["period_end"], entry["statement_type"]).date() >= since
        ]
        available.sort()
        return SourcedValue(
            value=available,
            source=_SOURCE,
            retrieved_at=now,
            available_at=now,
            period_start=since,
            period_end=None,
            validation_status=ValidationStatus.VALID if available else ValidationStatus.INSUFFICIENT,
        )

    def get_statement(self, ticker: str, fiscal_period: str) -> SourcedValue[FinancialStatementDocument]:
        now = dt.datetime.now(dt.UTC)
        periods = self._periods(ticker)
        entry = periods.get(fiscal_period)
        if entry is None or not entry["line_items"]:
            return SourcedValue(
                value=None,
                source=_SOURCE,
                retrieved_at=now,
                available_at=now,
                period_start=None,
                period_end=None,
                validation_status=ValidationStatus.INSUFFICIENT,
            )

        period_end = entry["period_end"]
        statement_type = entry["statement_type"]
        document = FinancialStatementDocument(
            company_ticker=ticker,
            statement_type=statement_type,
            fiscal_period=fiscal_period,
            source_format="json_csv_xlsx",
            currency="IDR",
            scale="unit",
            line_items=entry["line_items"],
            available_at_basis=f"estimated_period_end_plus_{_ANNUAL_LAG_DAYS if statement_type == 'annual' else _QUARTERLY_LAG_DAYS}_days",
        )
        available_at = _estimated_available_at(period_end, statement_type)
        return SourcedValue(
            value=document,
            source=_SOURCE,
            retrieved_at=now,
            available_at=available_at,
            period_start=None,
            period_end=period_end,
            validation_status=ValidationStatus.VALID,
        )
