"""Model registry, training runs, predictions, valuation and recommendation
outputs (spec §13-14, §10, §21).

Prediction/valuation payloads are JSONB because their shape is
horizon-dependent (a 20-day forecast is a return distribution; a 5-year
forecast is bear/base/bull scenarios, spec §14) -- the columns that matter
for filtering (company, as_of_date, horizon, model_version) stay relational.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base
from src.database.models.mixins import TimestampMixin


class ModelVersion(Base, TimestampMixin):
    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    branch: Mapped[str] = mapped_column(String(24), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    training_run_id: Mapped[int | None] = mapped_column(ForeignKey("training_runs.id"), nullable=True)
    artifact_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)  # MLflow model URI
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="challenger")
    # champion | challenger | retired


class TrainingRun(Base, TimestampMixin):
    __tablename__ = "training_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mlflow_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(nullable=False)
    completed_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    # running | succeeded | failed | rejected_by_gate
    data_period_start: Mapped[dt.date | None] = mapped_column(nullable=True)
    data_period_end: Mapped[dt.date | None] = mapped_column(nullable=True)
    validation_scheme: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # expanding_window | rolling_window | walk_forward | purged_cv
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    git_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Prediction(Base, TimestampMixin):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"), nullable=False, index=True)
    as_of_date: Mapped[dt.date] = mapped_column(nullable=False, index=True)
    horizon: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    # 5d | 20d | 60d | 120d | 252d | 3y | 5y
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # probability_positive_return, probability_beat_ihsg, expected_return, quantiles p10-p90, etc. (spec §14)
    uncertainty: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class ValuationResult(Base, TimestampMixin):
    __tablename__ = "valuation_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    as_of_date: Mapped[dt.date] = mapped_column(nullable=False, index=True)
    methods_used: Mapped[dict] = mapped_column(JSONB, nullable=False)  # {method_name: weight}
    fair_value_bear: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    fair_value_base: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    fair_value_bull: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    fair_value_conservative: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    sensitivity: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    data_quality_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)


class RecommendationResult(Base, TimestampMixin):
    __tablename__ = "recommendation_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    as_of_date: Mapped[dt.date] = mapped_column(nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(24), nullable=False)
    # LAYAK_DIBELI | AKUMULASI_BERTAHAP | TUNGGU_HARGA | HOLD | HINDARI | DATA_TIDAK_MENCUKUPI
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    scores: Mapped[dict] = mapped_column(JSONB, nullable=False)  # per §21 component scores
    guardrails_triggered: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    entry_zone: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    investment_style: Mapped[str | None] = mapped_column(String(32), nullable=True)
    suggested_horizon: Mapped[str | None] = mapped_column(String(32), nullable=True)
