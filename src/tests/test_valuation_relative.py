"""Unit tests for pure self-relative valuation arithmetic -- no DB, no network."""
from __future__ import annotations

import pytest

from src.valuation.relative import MIN_HISTORY_POINTS, combine_methods, percentile_fair_values


def test_percentile_fair_values_normal():
    result = percentile_fair_values(100.0, [8.0, 9.0, 10.0, 11.0, 12.0])
    assert result["p50_multiple"] == pytest.approx(10.0)
    assert result["base"] == pytest.approx(1000.0)  # 100 * p50
    assert result["bear"] < result["base"] < result["bull"]
    assert result["n_points"] == 5


def test_percentile_fair_values_too_few_points_is_not_applicable():
    result = percentile_fair_values(100.0, [8.0, 9.0])  # below MIN_HISTORY_POINTS
    assert len([8.0, 9.0]) < MIN_HISTORY_POINTS
    assert result["base"] is None
    assert result["bear"] is None
    assert result["bull"] is None


def test_percentile_fair_values_none_metric_is_not_applicable():
    result = percentile_fair_values(None, [8.0, 9.0, 10.0])
    assert result["base"] is None


def test_percentile_fair_values_non_positive_metric_is_not_applicable():
    # Negative EPS/book-value-per-share makes the multiple method
    # conventionally meaningless, same convention as ratios.py's P/E.
    result = percentile_fair_values(-5.0, [8.0, 9.0, 10.0])
    assert result["base"] is None
    result_zero = percentile_fair_values(0.0, [8.0, 9.0, 10.0])
    assert result_zero["base"] is None


def test_combine_methods_averages_when_both_available():
    pe = percentile_fair_values(100.0, [8.0, 10.0, 12.0])  # base = 1000
    pb = percentile_fair_values(50.0, [2.0, 3.0, 4.0])  # base = 150
    combined = combine_methods({"pe": pe, "pb": pb})
    assert combined["base"] == pytest.approx((1000.0 + 150.0) / 2)
    assert combined["methods_used"] == {"pe": 0.5, "pb": 0.5}


def test_combine_methods_conservative_is_minimum_bear_not_average():
    pe = percentile_fair_values(100.0, [8.0, 10.0, 12.0])
    pb = percentile_fair_values(50.0, [2.0, 3.0, 4.0])
    combined = combine_methods({"pe": pe, "pb": pb})
    assert combined["conservative"] == min(pe["bear"], pb["bear"])
    assert combined["conservative"] != pytest.approx(combined["bear"])  # not the same as the averaged bear-case


def test_combine_methods_uses_only_available_method():
    pe = percentile_fair_values(100.0, [8.0, 10.0, 12.0])
    pb_unavailable = percentile_fair_values(None, [])
    combined = combine_methods({"pe": pe, "pb": pb_unavailable})
    assert combined["methods_used"] == {"pe": 1.0}
    assert combined["base"] == pytest.approx(pe["base"])


def test_combine_methods_neither_available():
    combined = combine_methods({"pe": percentile_fair_values(None, []), "pb": percentile_fair_values(None, [])})
    assert combined["methods_used"] == {}
    assert combined["base"] is None
    assert combined["conservative"] is None
