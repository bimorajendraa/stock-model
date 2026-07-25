"""Classification evaluation metrics (spec section 19)."""
from __future__ import annotations

import dataclasses

import numpy as np
from sklearn.metrics import (
    balanced_accuracy_score,
    brier_score_loss,
    f1_score,
    matthews_corrcoef,
    precision_score,
    recall_score,
    roc_auc_score,
)


@dataclasses.dataclass
class ClassificationMetrics:
    precision: float
    recall: float
    f1: float
    roc_auc: float | None
    balanced_accuracy: float
    mcc: float
    brier_score: float
    n_samples: int
    positive_rate: float


def evaluate_classification(y_true: np.ndarray, y_pred: np.ndarray, y_proba: np.ndarray) -> ClassificationMetrics:
    """``y_proba`` is the predicted probability of the positive class."""
    try:
        roc_auc = float(roc_auc_score(y_true, y_proba)) if len(np.unique(y_true)) > 1 else None
    except ValueError:
        roc_auc = None

    return ClassificationMetrics(
        precision=float(precision_score(y_true, y_pred, zero_division=0)),
        recall=float(recall_score(y_true, y_pred, zero_division=0)),
        f1=float(f1_score(y_true, y_pred, zero_division=0)),
        roc_auc=roc_auc,
        balanced_accuracy=float(balanced_accuracy_score(y_true, y_pred)),
        mcc=float(matthews_corrcoef(y_true, y_pred)) if len(np.unique(y_pred)) > 1 else 0.0,
        brier_score=float(brier_score_loss(y_true, y_proba)),
        n_samples=len(y_true),
        positive_rate=float(np.mean(y_true)),
    )
