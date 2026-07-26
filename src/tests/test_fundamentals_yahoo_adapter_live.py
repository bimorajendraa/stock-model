"""Live-network tests for the Yahoo fundamentals adapter -- hits the real
yfinance API (no mock, no fixture), consistent with how every other
external call in this project is verified. No database needed, but
marked ``integration`` anyway (excluded from the default fast unit run)
because a live network call is exactly the kind of thing that shouldn't
run on every ``pytest -v``.
"""
from __future__ import annotations

import datetime as dt

import pytest

from src.data_sources.base import ValidationStatus
from src.data_sources.fundamentals.taxonomy import ACCOUNT_CODE_SECTIONS
from src.data_sources.fundamentals.yahoo_finance import YahooFinanceFundamentalsAdapter

pytestmark = pytest.mark.integration


def test_list_available_statements_bbca_real():
    adapter = YahooFinanceFundamentalsAdapter()
    result = adapter.list_available_statements("BBCA", dt.date(2000, 1, 1))
    assert result.validation_status == ValidationStatus.VALID
    assert result.value  # real fiscal periods, not empty
    assert any(fp.endswith("FY") for fp in result.value)
    assert any("Q" in fp for fp in result.value)


def test_get_statement_bbca_annual_real_values_are_plausible():
    adapter = YahooFinanceFundamentalsAdapter()
    listed = adapter.list_available_statements("BBCA", dt.date(2000, 1, 1))
    annual_periods = sorted(fp for fp in listed.value if fp.endswith("FY"))
    assert annual_periods
    result = adapter.get_statement("BBCA", annual_periods[-1])
    assert result.validation_status == ValidationStatus.VALID
    doc = result.value
    assert doc.currency == "IDR"
    # BBCA is one of IDX's largest banks -- net income and total assets
    # should be in the trillions of IDR, not a fabricated/placeholder
    # small number and not accidentally reported in a different unit.
    assert doc.line_items["net_income"] > 1e12
    assert doc.line_items["total_assets"] > 1e14
    assert doc.line_items["shares_outstanding"] > 1e10  # BBCA has ~123B shares
    # every returned account_code must be a real taxonomy entry
    assert set(doc.line_items) <= set(ACCOUNT_CODE_SECTIONS)


def test_get_statement_available_at_is_after_period_end():
    adapter = YahooFinanceFundamentalsAdapter()
    listed = adapter.list_available_statements("BBCA", dt.date(2000, 1, 1))
    fiscal_period = max(fp for fp in listed.value if fp.endswith("FY"))
    result = adapter.get_statement("BBCA", fiscal_period)
    assert result.available_at.date() > result.period_end


def test_bank_has_no_cost_of_revenue_or_gross_profit():
    # Banks don't report COGS/gross profit -- must be omitted, never
    # fabricated as 0 or copied from another line item.
    adapter = YahooFinanceFundamentalsAdapter()
    listed = adapter.list_available_statements("BBCA", dt.date(2000, 1, 1))
    fiscal_period = max(fp for fp in listed.value if fp.endswith("FY"))
    result = adapter.get_statement("BBCA", fiscal_period)
    assert "cost_of_revenue" not in result.value.line_items
    assert "gross_profit" not in result.value.line_items


def test_non_bank_has_cost_of_revenue_and_gross_profit():
    adapter = YahooFinanceFundamentalsAdapter()
    listed = adapter.list_available_statements("TLKM", dt.date(2000, 1, 1))
    fiscal_period = max(fp for fp in listed.value if fp.endswith("FY"))
    result = adapter.get_statement("TLKM", fiscal_period)
    assert "cost_of_revenue" in result.value.line_items
    assert "gross_profit" in result.value.line_items


def test_unknown_ticker_returns_insufficient():
    adapter = YahooFinanceFundamentalsAdapter()
    result = adapter.list_available_statements("ZZZZZ_NOT_A_REAL_TICKER", dt.date(2000, 1, 1))
    assert result.validation_status == ValidationStatus.INSUFFICIENT
    assert result.value == []
