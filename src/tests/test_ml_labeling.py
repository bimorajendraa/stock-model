"""Unit tests for point-in-time labeling."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.ml.datasets.labeling import (
    build_labels,
    compute_cross_sectional_quantile,
    compute_direction_labels,
    compute_forward_returns,
)


def _series(values):
    return pd.Series(values, index=pd.date_range("2026-01-01", periods=len(values), freq="D"))


def test_forward_return_hand_computed():
    close = _series([100, 110, 121, 133.1])
    result = compute_forward_returns(close, horizons=(1, 2))
    assert result["fwd_return_1d"].iloc[0] == pytest.approx(0.10)  # 110/100 - 1
    assert result["fwd_return_2d"].iloc[0] == pytest.approx(0.21)  # 121/100 - 1


def test_forward_return_nan_at_end_of_history():
    close = _series([100, 110, 121])
    result = compute_forward_returns(close, horizons=(5,))
    assert result["fwd_return_5d"].isna().all()  # no row has 5 future days available


def test_direction_label_matches_sign_of_return():
    close = _series([100, 110, 90, 90])
    fwd = compute_forward_returns(close, horizons=(1,))
    direction = compute_direction_labels(fwd)
    assert direction["fwd_return_1d"].iloc[0] == 1.0  # 100 -> 110, up
    assert direction["fwd_return_1d"].iloc[1] == 0.0  # 110 -> 90, down


def test_direction_label_preserves_nan():
    close = _series([100, 110])
    fwd = compute_forward_returns(close, horizons=(5,))
    direction = compute_direction_labels(fwd)
    assert direction["fwd_return_5d"].isna().all()


def test_build_labels_has_expected_columns():
    close = _series(np.linspace(100, 200, 30))
    result = build_labels(close, horizons=(5, 20))
    assert set(result.columns) == {"fwd_return_5d", "fwd_return_20d", "direction_5d", "direction_20d"}


def test_cross_sectional_quantile_ranks_correctly():
    dates = pd.date_range("2026-01-01", periods=2, freq="D")
    returns_by_ticker = {
        "A": pd.Series([0.10, 0.05], index=dates),
        "B": pd.Series([0.02, 0.20], index=dates),
        "C": pd.Series([-0.05, -0.01], index=dates),
    }
    result = compute_cross_sectional_quantile(returns_by_ticker, "fwd_return_5d")
    # Day 1: A=0.10 (highest), B=0.02 (middle), C=-0.05 (lowest)
    assert result["A"].iloc[0] == pytest.approx(1.0)
    assert result["C"].iloc[0] == pytest.approx(1 / 3)
    # Day 2: B=0.20 (highest), A=0.05 (middle), C=-0.01 (lowest)
    assert result["B"].iloc[1] == pytest.approx(1.0)
    assert result["C"].iloc[1] == pytest.approx(1 / 3)
