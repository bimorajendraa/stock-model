"""Regression evaluation metrics (spec section 19)."""
from __future__ import annotations

import dataclasses

import numpy as np
from scipy import stats
from sklearn.metrics import mean_absolute_error, median_absolute_error, root_mean_squared_error


@dataclasses.dataclass
class RegressionMetrics:
    mae: float
    rmse: float
    median_ae: float
    correlation: float | None
    rank_correlation: float | None
    n_samples: int


def evaluate_regression(y_true: np.ndarray, y_pred: np.ndarray) -> RegressionMetrics:
    correlation = None
    rank_correlation = None
    if len(y_true) > 1 and np.std(y_true) > 0 and np.std(y_pred) > 0:
        correlation = float(np.corrcoef(y_true, y_pred)[0, 1])
        rank_correlation = float(stats.spearmanr(y_true, y_pred).correlation)

    return RegressionMetrics(
        mae=float(mean_absolute_error(y_true, y_pred)),
        rmse=float(root_mean_squared_error(y_true, y_pred)),
        median_ae=float(median_absolute_error(y_true, y_pred)),
        correlation=correlation,
        rank_correlation=rank_correlation,
        n_samples=len(y_true),
    )
