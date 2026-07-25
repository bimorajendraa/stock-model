"""Ties together dataset assembly, splitting, baseline fitting, and
evaluation (spec sections 13, 17, 19, 32). Trains every baseline on the
SAME train split and evaluates all of them on the SAME validation/test
splits, so comparisons are apples-to-apples.

Rows with any missing feature (e.g. sma_200 before 200 days of history
exist) are dropped rather than imputed with a placeholder value -- a
model should never be handed a fabricated "0" that looks like real data
(spec section 2.12/6.3).
"""
from __future__ import annotations

import dataclasses

import pandas as pd
from sqlalchemy.orm import Session

from src.ml.baselines.simple import MovingAverageRuleClassifier, NaiveBaseRateClassifier
from src.ml.baselines.sklearn_models import make_logistic_regression, make_random_forest, make_simple_mlp
from src.ml.datasets.build import build_labeled_dataset, split_dataset
from src.ml.evaluation.classification import ClassificationMetrics, evaluate_classification

NON_FEATURE_COLUMNS = {"company_id", "feature_date", "ticker"}
# "close" is carried through build_labeled_dataset as a passthrough column
# for the moving-average rule baseline (needs the raw price to compare
# against its SMA) -- deliberately excluded from the indicator feature set
# handed to the learned models. Logistic regression's L2 penalty treats
# feature scale as meaningful; an unscaled raw price in the thousands next
# to indicators like RSI (0-100) or ratios (~1.0) would be regularized
# very differently than intended.
PASSTHROUGH_ONLY_COLUMNS = {"close"}


def _indicator_feature_columns(df: pd.DataFrame) -> list[str]:
    return [
        c
        for c in df.columns
        if c not in NON_FEATURE_COLUMNS
        and c not in PASSTHROUGH_ONLY_COLUMNS
        and not c.startswith("fwd_return_")
        and not c.startswith("direction_")
    ]


@dataclasses.dataclass
class BaselineComparisonResult:
    model_name: str
    train: ClassificationMetrics
    validation: ClassificationMetrics
    test: ClassificationMetrics


def run_baseline_comparison(
    session: Session, tickers: list[str], horizon_days: int = 20, embargo_days: int = 10
) -> tuple[list[BaselineComparisonResult], dict]:
    df = build_labeled_dataset(session, tickers, horizons=(horizon_days,))
    if df.empty:
        return [], {"error": "empty dataset"}

    feature_cols = _indicator_feature_columns(df)
    direction_col = f"direction_{horizon_days}d"
    df = df.dropna(subset=[*feature_cols, "close", direction_col])

    parts, split = split_dataset(df, horizon_days, embargo_days)
    train, validation, test = parts["train"], parts["validation"], parts["test"]

    info = {
        "horizon_days": horizon_days,
        "n_features": len(feature_cols),
        "n_train": len(train),
        "n_validation": len(validation),
        "n_test": len(test),
        "split": split,
        "train_positive_rate": float(train[direction_col].mean()) if len(train) else None,
    }

    if len(train) == 0 or len(validation) == 0 or len(test) == 0:
        return [], {**info, "error": "one or more splits are empty"}

    y_train, y_val, y_test = train[direction_col], validation[direction_col], test[direction_col]

    # rule_cols: indicator features + raw close, for the moving-average
    # rule baseline only. Every other model gets feature_cols (no close).
    rule_cols = [*feature_cols, "close"]
    model_feature_cols = {
        "naive_base_rate": feature_cols,
        "moving_average_rule": rule_cols,
        "logistic_regression": feature_cols,
        "random_forest": feature_cols,
        "simple_mlp": feature_cols,
    }
    models = {
        "naive_base_rate": NaiveBaseRateClassifier(),
        "moving_average_rule": MovingAverageRuleClassifier(sma_column="sma_20", close_column="close"),
        "logistic_regression": make_logistic_regression(),
        "random_forest": make_random_forest(),
        "simple_mlp": make_simple_mlp(),
    }

    results: list[BaselineComparisonResult] = []
    for name, model in models.items():
        cols = model_feature_cols[name]
        X_train, X_val, X_test = train[cols], validation[cols], test[cols]

        model.fit(X_train, y_train)

        # Train-set metrics too, not just val/test: spec section 18 requires
        # reporting the train/validation gap as overfitting evidence, not
        # just claiming a model isn't overfit.
        train_proba = model.predict_proba(X_train)[:, 1]
        train_pred = (train_proba >= 0.5).astype(int)
        train_metrics = evaluate_classification(y_train.to_numpy(), train_pred, train_proba)

        val_proba = model.predict_proba(X_val)[:, 1]
        val_pred = (val_proba >= 0.5).astype(int)
        val_metrics = evaluate_classification(y_val.to_numpy(), val_pred, val_proba)

        test_proba = model.predict_proba(X_test)[:, 1]
        test_pred = (test_proba >= 0.5).astype(int)
        test_metrics = evaluate_classification(y_test.to_numpy(), test_pred, test_proba)

        results.append(
            BaselineComparisonResult(model_name=name, train=train_metrics, validation=val_metrics, test=test_metrics)
        )

    return results, info
