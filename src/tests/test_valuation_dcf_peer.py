"""Unit tests for peer-relative valuation and explicit-assumption DCF."""
from __future__ import annotations

import pytest

from src.valuation.dcf import DCFInputs, discounted_cash_flow
from src.valuation.peer import MIN_PEERS, peer_multiple_fair_values


def test_peer_multiple_uses_peer_percentiles():
    result = peer_multiple_fair_values(100.0, [8.0, 10.0, 12.0, 14.0])
    assert result["n_peers"] == 4
    assert result["base"] == pytest.approx(1100.0)
    assert result["bear"] < result["base"] < result["bull"]


def test_peer_multiple_requires_minimum_real_peers():
    result = peer_multiple_fair_values(100.0, [8.0] * (MIN_PEERS - 1))
    assert result["base"] is None


def test_dcf_returns_ordered_scenarios_and_full_sensitivity_grid():
    result = discounted_cash_flow(
        DCFInputs(
            base_free_cash_flow=100.0,
            cash=50.0,
            debt=20.0,
            shares_outstanding=10.0,
            discount_rate=0.12,
            near_term_growth_rate=0.06,
            terminal_growth_rate=0.03,
            projection_years=5,
        )
    )
    assert result["bear"] < result["base"] < result["bull"]
    assert result["conservative"] == result["bear"]
    assert len(result["grid"]) == 9
    assert result["inputs"]["discount_rate"] == 0.12


def test_dcf_refuses_invalid_or_non_positive_inputs():
    result = discounted_cash_flow(
        DCFInputs(
            base_free_cash_flow=-1.0,
            cash=0.0,
            debt=0.0,
            shares_outstanding=10.0,
            discount_rate=0.10,
            near_term_growth_rate=0.05,
            terminal_growth_rate=0.03,
        )
    )
    assert result["base"] is None

    invalid_spread = discounted_cash_flow(
        DCFInputs(
            base_free_cash_flow=100.0,
            cash=0.0,
            debt=0.0,
            shares_outstanding=10.0,
            discount_rate=0.03,
            near_term_growth_rate=0.05,
            terminal_growth_rate=0.03,
        )
    )
    assert invalid_spread["base"] is None
