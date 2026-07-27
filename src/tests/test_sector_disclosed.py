"""Unit tests for disclosed bank/mining metric arithmetic."""
from __future__ import annotations

import pytest

from src.features.sector.disclosed import compute_bank_metrics, compute_mining_metrics


def test_bank_metrics_prefer_reported_ratios_and_normalize_decimal_percent():
    metrics = compute_bank_metrics(
        {
            "npl_gross_ratio_reported": 0.021,
            "net_interest_margin_reported": 0.054,
            "capital_adequacy_ratio_reported": 28.5,
        },
        annual=True,
    )
    assert metrics["npl_gross_pct"] == pytest.approx((2.1, "percent"))
    assert metrics["net_interest_margin_pct"] == pytest.approx((5.4, "percent"))
    assert metrics["capital_adequacy_ratio_pct"] == pytest.approx((28.5, "percent"))


def test_bank_metrics_derive_only_from_available_disclosed_inputs():
    metrics = compute_bank_metrics(
        {
            "non_performing_loans_gross": 20.0,
            "gross_loans": 1000.0,
            "customer_deposits": 1250.0,
            "current_accounts": 300.0,
            "savings_accounts": 200.0,
            "net_interest_income": 50.0,
            "earning_assets": 1100.0,
            "regulatory_capital": 250.0,
            "risk_weighted_assets": 1000.0,
        },
        {"earning_assets": 900.0},
        annual=True,
    )
    assert metrics["npl_gross_pct"][0] == pytest.approx(2.0)
    assert metrics["loan_to_deposit_ratio_pct"][0] == pytest.approx(80.0)
    assert metrics["casa_ratio_pct"][0] == pytest.approx(40.0)
    assert metrics["net_interest_margin_pct"][0] == pytest.approx(5.0)
    assert metrics["capital_adequacy_ratio_pct"][0] == pytest.approx(25.0)
    assert "npl_net_pct" not in metrics


def test_quarterly_nim_is_not_derived_without_reported_ratio():
    metrics = compute_bank_metrics(
        {"net_interest_income": 10.0, "earning_assets": 100.0},
        {"earning_assets": 90.0},
        annual=False,
    )
    assert "net_interest_margin_pct" not in metrics


def test_mining_reserve_life_requires_matching_units():
    facts = {"proven_probable_reserves": 500.0, "annual_production": 50.0}
    matching = compute_mining_metrics(
        facts,
        {"proven_probable_reserves": "million_tonnes", "annual_production": "million_tonnes"},
    )
    mismatched = compute_mining_metrics(
        facts,
        {"proven_probable_reserves": "million_tonnes", "annual_production": "million_ounces"},
    )
    assert matching["reserve_life_years"] == pytest.approx((10.0, "years"))
    assert "reserve_life_years" not in mismatched
