"""Unit tests for pure fundamental-ratio arithmetic -- no DB, no network."""
from __future__ import annotations

from src.features.fundamentals.ratios import (
    RATIO_NAMES,
    compute_all_ratios,
    compute_price_dependent_ratios,
    compute_statement_ratios,
    safe_div,
)


def test_safe_div_normal():
    assert safe_div(10.0, 4.0) == 2.5


def test_safe_div_zero_denominator_is_none():
    assert safe_div(10.0, 0.0) is None


def test_safe_div_missing_inputs_are_none():
    assert safe_div(None, 4.0) is None
    assert safe_div(10.0, None) is None


def test_statement_ratios_full_non_bank_company():
    items = {
        "revenue": 1000.0,
        "gross_profit": 400.0,
        "operating_income": 200.0,
        "net_income": 100.0,
        "total_equity": 500.0,
        "total_assets": 2000.0,
        "total_debt": 300.0,
        "current_assets": 600.0,
        "current_liabilities": 300.0,
        "free_cash_flow": 150.0,
        "operating_cash_flow": 180.0,
        "shares_outstanding": 1000.0,
    }
    ratios = compute_statement_ratios(items)
    assert ratios["gross_margin"] == 0.4
    assert ratios["operating_margin"] == 0.2
    assert ratios["net_margin"] == 0.1
    assert ratios["roe"] == 0.2
    assert ratios["roa"] == 0.05
    assert ratios["debt_to_equity"] == 0.6
    assert ratios["debt_to_assets"] == 0.15
    assert ratios["current_ratio"] == 2.0
    assert ratios["fcf_margin"] == 0.15
    assert ratios["ocf_margin"] == 0.18
    assert ratios["book_value_per_share"] == 0.5


def test_statement_ratios_bank_missing_inputs_are_not_applicable():
    # A bank's real statement (spec section 3.5 sector-dependent shape):
    # no gross_profit/operating_income/current_assets/current_liabilities.
    items = {
        "revenue": 1000.0,
        "net_income": 100.0,
        "total_equity": 500.0,
        "total_assets": 2000.0,
        "total_debt": 50.0,
    }
    ratios = compute_statement_ratios(items)
    assert ratios["gross_margin"] is None
    assert ratios["operating_margin"] is None
    assert ratios["current_ratio"] is None
    # still computable from what IS reported
    assert ratios["net_margin"] == 0.1
    assert ratios["roe"] == 0.2
    assert ratios["roa"] == 0.05


def test_price_dependent_ratios_normal():
    items = {"total_equity": 500.0, "shares_outstanding": 1000.0, "eps_diluted": 2.0}
    ratios = compute_price_dependent_ratios(items, price=20.0)
    assert ratios["price_to_book"] == 40.0  # 20 / (500/1000)
    assert ratios["price_to_earnings"] == 10.0  # 20 / 2.0


def test_price_dependent_ratios_no_price_is_not_applicable():
    items = {"total_equity": 500.0, "shares_outstanding": 1000.0, "eps_diluted": 2.0}
    ratios = compute_price_dependent_ratios(items, price=None)
    assert ratios["price_to_book"] is None
    assert ratios["price_to_earnings"] is None


def test_price_to_earnings_negative_eps_is_not_applicable():
    # Standard financial-data-provider convention: negative/zero earnings
    # make P/E conventionally undefined, not a mechanically negative number.
    items = {"eps_diluted": -1.5}
    ratios = compute_price_dependent_ratios(items, price=20.0)
    assert ratios["price_to_earnings"] is None


def test_price_dependent_ratios_falls_back_to_basic_eps():
    items = {"eps_basic": 2.0}
    ratios = compute_price_dependent_ratios(items, price=20.0)
    assert ratios["price_to_earnings"] == 10.0


def test_compute_all_ratios_returns_every_ratio_name():
    ratios = compute_all_ratios({}, None)
    assert set(ratios) == set(RATIO_NAMES)
    assert all(v is None for v in ratios.values())  # no inputs -> everything not_applicable
