"""Sector-specific metrics registry (spec §3.5).

Deliberately generic (metric_name/value) rather than one column per metric:
banking NPL/NIM/CASA, mining stripping-ratio/cash-cost, telco ARPU/churn,
etc. are wildly different shapes. Which metric names are expected/required
for a given sector lives in ``configs/sector_metrics/*.yaml`` (Tahap 3), not
in the schema -- so new sectors can be added without a migration.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base
from src.database.models.mixins import SourceLineageMixin, TimestampMixin


class SectorSpecificMetric(Base, TimestampMixin, SourceLineageMixin):
    __tablename__ = "sector_specific_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    sector_registry_id: Mapped[int] = mapped_column(ForeignKey("sector_registry.id"), nullable=False, index=True)
    metric_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    value: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    value_text: Mapped[str | None] = mapped_column(String(256), nullable=True)  # for non-numeric metrics
