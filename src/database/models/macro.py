"""Macroeconomic and industry/commodity/index time series (spec §3.4)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base
from src.database.models.mixins import SourceLineageMixin, TimestampMixin


class MacroSeries(Base, TimestampMixin, SourceLineageMixin):
    """BI-Rate, inflation, USD/IDR, Fed Funds Rate, bond yields, etc."""

    __tablename__ = "macro_series"
    __table_args__ = (UniqueConstraint("series_code", "observation_date", "source_id", name="uq_macro_series_obs"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    series_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    series_name: Mapped[str] = mapped_column(String(256), nullable=False)
    observation_date: Mapped[dt.date] = mapped_column(nullable=False, index=True)
    value: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    unit_of_measure: Mapped[str] = mapped_column(String(32), nullable=False)


class IndustrySeries(Base, TimestampMixin, SourceLineageMixin):
    """Commodity prices, IHSG, sector indices, and other market-wide series
    that are not tied to a single company."""

    __tablename__ = "industry_series"
    __table_args__ = (UniqueConstraint("series_code", "observation_date", "source_id", name="uq_industry_series_obs"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    series_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    series_name: Mapped[str] = mapped_column(String(256), nullable=False)
    observation_date: Mapped[dt.date] = mapped_column(nullable=False, index=True)
    value: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    unit_of_measure: Mapped[str] = mapped_column(String(32), nullable=False)
