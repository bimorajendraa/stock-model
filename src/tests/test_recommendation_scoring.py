"""Unit tests for pure recommendation scoring logic -- no DB, no network."""
from __future__ import annotations

from src.recommendation.scoring import (
    LABEL_AKUMULASI_BERTAHAP,
    LABEL_DATA_TIDAK_MENCUKUPI,
    LABEL_HINDARI,
    LABEL_HOLD,
    LABEL_LAYAK_DIBELI,
    LABEL_TUNGGU_HARGA,
    QUALITY_HEALTHY,
    QUALITY_MIXED,
    QUALITY_WEAK,
    VALUATION_FAIR,
    VALUATION_OVERVALUED,
    VALUATION_UNDERVALUED,
    classify_fundamental_quality,
    classify_valuation_position,
    combine_recommendation,
    compute_confidence,
)


def test_classify_valuation_position_below_bear_is_undervalued():
    assert classify_valuation_position(current_price=80.0, fair_value_bear=100.0, fair_value_bull=150.0) == VALUATION_UNDERVALUED


def test_classify_valuation_position_above_bull_is_overvalued():
    assert classify_valuation_position(current_price=200.0, fair_value_bear=100.0, fair_value_bull=150.0) == VALUATION_OVERVALUED


def test_classify_valuation_position_between_is_fair():
    assert classify_valuation_position(current_price=120.0, fair_value_bear=100.0, fair_value_bull=150.0) == VALUATION_FAIR


def test_classify_valuation_position_missing_input_is_none():
    assert classify_valuation_position(None, 100.0, 150.0) is None
    assert classify_valuation_position(120.0, None, 150.0) is None
    assert classify_valuation_position(120.0, 100.0, None) is None


def test_classify_fundamental_quality_healthy():
    assert classify_fundamental_quality(net_margin=0.15, roe=0.20, debt_to_equity=0.5) == QUALITY_HEALTHY


def test_classify_fundamental_quality_weak_when_unprofitable():
    assert classify_fundamental_quality(net_margin=-0.05, roe=0.20, debt_to_equity=0.5) == QUALITY_WEAK
    assert classify_fundamental_quality(net_margin=0.15, roe=-0.02, debt_to_equity=0.5) == QUALITY_WEAK


def test_classify_fundamental_quality_mixed_when_roe_low_or_leverage_high():
    assert classify_fundamental_quality(net_margin=0.05, roe=0.05, debt_to_equity=0.5) == QUALITY_MIXED
    assert classify_fundamental_quality(net_margin=0.15, roe=0.20, debt_to_equity=1.5) == QUALITY_MIXED


def test_classify_fundamental_quality_debt_to_equity_not_applicable_still_classifiable():
    # A bank has no comparable debt_to_equity in this taxonomy -- must not
    # block classification (spec: not_applicable != missing-and-fatal).
    assert classify_fundamental_quality(net_margin=0.15, roe=0.20, debt_to_equity=None) == QUALITY_HEALTHY


def test_classify_fundamental_quality_missing_profitability_is_none():
    assert classify_fundamental_quality(net_margin=None, roe=0.20, debt_to_equity=0.5) is None
    assert classify_fundamental_quality(net_margin=0.15, roe=None, debt_to_equity=0.5) is None


def test_combine_recommendation_undervalued_healthy_is_layak_dibeli():
    assert combine_recommendation(VALUATION_UNDERVALUED, QUALITY_HEALTHY) == LABEL_LAYAK_DIBELI


def test_combine_recommendation_undervalued_mixed_is_akumulasi_bertahap():
    assert combine_recommendation(VALUATION_UNDERVALUED, QUALITY_MIXED) == LABEL_AKUMULASI_BERTAHAP


def test_combine_recommendation_weak_fundamentals_always_hindari():
    # Cheap-but-weak (value trap), fair-but-weak, expensive-and-weak --
    # all HINDARI regardless of valuation.
    assert combine_recommendation(VALUATION_UNDERVALUED, QUALITY_WEAK) == LABEL_HINDARI
    assert combine_recommendation(VALUATION_FAIR, QUALITY_WEAK) == LABEL_HINDARI
    assert combine_recommendation(VALUATION_OVERVALUED, QUALITY_WEAK) == LABEL_HINDARI


def test_combine_recommendation_overvalued_healthy_is_tunggu_harga():
    assert combine_recommendation(VALUATION_OVERVALUED, QUALITY_HEALTHY) == LABEL_TUNGGU_HARGA


def test_combine_recommendation_fair_healthy_is_hold():
    assert combine_recommendation(VALUATION_FAIR, QUALITY_HEALTHY) == LABEL_HOLD


def test_combine_recommendation_missing_input_is_data_tidak_mencukupi():
    assert combine_recommendation(None, QUALITY_HEALTHY) == LABEL_DATA_TIDAK_MENCUKUPI
    assert combine_recommendation(VALUATION_UNDERVALUED, None) == LABEL_DATA_TIDAK_MENCUKUPI
    assert combine_recommendation(None, None) == LABEL_DATA_TIDAK_MENCUKUPI


def test_compute_confidence_full_data():
    assert compute_confidence(valuation_data_quality=1.0, n_fundamental_inputs=3) == 1.0


def test_compute_confidence_missing_valuation_is_zero():
    assert compute_confidence(valuation_data_quality=None, n_fundamental_inputs=3) == 0.0


def test_compute_confidence_partial_fundamental_data():
    result = compute_confidence(valuation_data_quality=1.0, n_fundamental_inputs=1, n_fundamental_inputs_target=3)
    assert result == round((1.0 + 1 / 3) / 2, 4)
