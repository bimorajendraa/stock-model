"""Non-learned baselines (spec section 13): every real model must beat
these, or it's not worth using (spec section 32 quality gate). Both
implement a minimal fit/predict_proba interface so they're interchangeable
with the sklearn-backed models in evaluation code.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


class NaiveBaseRateClassifier:
    """Predicts the same probability for every row: the fraction of
    positive labels seen in the training set. The single simplest
    possible "model" -- if a real model can't beat this, it has learned
    nothing useful from the features."""

    def __init__(self) -> None:
        self.base_rate_: float | None = None

    def fit(self, X: pd.DataFrame, y: pd.Series) -> NaiveBaseRateClassifier:
        self.base_rate_ = float(y.mean())
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if self.base_rate_ is None:
            raise RuntimeError("call fit() first")
        p = np.full(len(X), self.base_rate_)
        return np.column_stack([1 - p, p])

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)


class MovingAverageRuleClassifier:
    """Rule-based, not learned: predicts "up" whenever close is above its
    own SMA (a specific column in X), "down" otherwise. Confidence is
    fixed at 0.5 +/- a constant margin rather than a real probability --
    this is a technical trading heuristic being used as a sanity-check
    baseline, not a calibrated model."""

    def __init__(self, sma_column: str = "sma_20", close_column: str = "close", margin: float = 0.1) -> None:
        self.sma_column = sma_column
        self.close_column = close_column
        self.margin = margin

    def fit(self, X: pd.DataFrame, y: pd.Series) -> MovingAverageRuleClassifier:
        return self  # nothing to learn

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        above = (X[self.close_column] > X[self.sma_column]).to_numpy()
        p = np.where(above, 0.5 + self.margin, 0.5 - self.margin)
        return np.column_stack([1 - p, p])

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return (X[self.close_column] > X[self.sma_column]).astype(int).to_numpy()


class NaivePersistenceRegressor:
    """Predicts 0 forward return for every row -- the simplest possible
    regression baseline ("expect no change"). A real regressor that can't
    beat this on MAE/RMSE has learned nothing directionally useful."""

    def fit(self, X: pd.DataFrame, y: pd.Series) -> NaivePersistenceRegressor:
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return np.zeros(len(X))
