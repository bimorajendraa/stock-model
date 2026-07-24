"""Feature store (spec §7, §8).

Long/narrow format (one row per company x date x feature_name) rather than
one column per indicator: §7-8 enumerate 100+ technical and fundamental
features, and sector-specific ones (§3.5) are open-ended. A wide table
would require a migration for every new indicator; this doesn't.

``model_features`` is the assembled, versioned snapshot actually fed to
training/inference -- a JSONB blob keyed by feature name, because its shape
is branch-specific (technical vs fundamental vs sentiment vs macro) and it
is written once per (company, as_of, feature_set_version) rather than
queried column-by-column.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base
from src.database.models.mixins import TimestampMixin


class TechnicalFeature(Base, TimestampMixin):
    __tablename__ = "technical_features"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    feature_date: Mapped[dt.date] = mapped_column(nullable=False, index=True)
    feature_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    value: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    feature_set_version: Mapped[str] = mapped_column(String(32), nullable=False)


class FundamentalFeature(Base, TimestampMixin):
    __tablename__ = "fundamental_features"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    as_of_date: Mapped[dt.date] = mapped_column(nullable=False, index=True)
    # as_of_date = available_at of the statement this feature was computable from,
    # never period_end -- point-in-time discipline (spec §16).
    feature_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    value: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    feature_set_version: Mapped[str] = mapped_column(String(32), nullable=False)


class ModelFeatures(Base, TimestampMixin):
    __tablename__ = "model_features"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    as_of_date: Mapped[dt.date] = mapped_column(nullable=False, index=True)
    branch: Mapped[str] = mapped_column(String(24), nullable=False)
    # technical | fundamental | sentiment | macro_industry | meta
    feature_set_version: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
