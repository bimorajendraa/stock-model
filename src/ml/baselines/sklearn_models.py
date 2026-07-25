"""Classical ML baselines (spec section 13), built before any deep
learning. Defaults are deliberately conservative -- capacity limits and
regularization per spec section 18 (prevent overfitting on a dataset this
small: ~90K rows for 50 companies over ~10 years is not a lot of truly
independent samples once autocorrelation is considered).

Logistic regression and the MLP are wrapped in a ``Pipeline`` with
``StandardScaler`` -- the 36 technical indicators span wildly different
scales (RSI ~0-100, ratios ~1.0, OBV/AD-line in the millions), which
without scaling both slows convergence and skews the L2 penalty toward
punishing large-scale features regardless of their actual importance.
``Pipeline.fit`` fits the scaler on the training fold only and reuses it
to transform validation/test -- exactly spec section 6.4's requirement
("Scaler hanya boleh di-fit pada training fold").
"""
from __future__ import annotations

from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

RANDOM_SEED = 42  # spec section 18: seed control for reproducibility


def make_logistic_regression() -> Pipeline:
    return Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "model",
                LogisticRegression(
                    C=0.1,  # strong L2 regularization (small C = more regularization)
                    max_iter=1000,
                    random_state=RANDOM_SEED,
                ),
            ),
        ]
    )


def make_random_forest() -> RandomForestClassifier:
    # Tree splits are scale-invariant -- no scaler needed.
    return RandomForestClassifier(
        n_estimators=200,
        max_depth=6,  # capacity limit -- avoid memorizing a small dataset
        min_samples_leaf=20,
        random_state=RANDOM_SEED,
        n_jobs=-1,
    )


def make_simple_mlp() -> Pipeline:
    return Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "model",
                MLPClassifier(
                    hidden_layer_sizes=(16,),  # deliberately small -- "simple MLP" per spec, not a deep network
                    alpha=0.01,  # L2 regularization
                    early_stopping=True,
                    max_iter=500,
                    random_state=RANDOM_SEED,
                ),
            ),
        ]
    )
