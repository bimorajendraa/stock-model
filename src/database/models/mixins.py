"""Reusable column mixins.

``SourceLineageMixin`` implements the mandatory provenance fields from the
master spec (§4 / §11): every fact table must record where a number came
from, when it was fetched, when it was actually publicly available, what
period it covers, and whether it passed validation. Point-in-time
correctness (never using data before its ``available_at``) depends on this
being present everywhere -- it is not optional decoration.
"""
from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, declared_attr, mapped_column


class QualityStatus(str, enum.Enum):
    PENDING = "pending"
    VALID = "valid"
    SUSPECT = "suspect"
    INVALID = "invalid"
    INSUFFICIENT = "data_tidak_mencukupi"


class TimestampMixin:
    """Row bookkeeping (not data lineage) -- when *our* record was written."""

    created_at: Mapped[dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default="now()", nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default="now()",
        onupdate=lambda: dt.datetime.now(dt.UTC),
        nullable=False,
    )


class SourceLineageMixin:
    """Mandatory provenance columns for every fact table (spec §4, §11)."""

    @declared_attr
    def source_id(cls) -> Mapped[int]:
        return mapped_column(ForeignKey("data_source_registry.id"), nullable=False, index=True)

    retrieved_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    available_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, index=True)

    period_start: Mapped[dt.date | None] = mapped_column(nullable=True)
    period_end: Mapped[dt.date | None] = mapped_column(nullable=True, index=True)

    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="unit")

    is_restated: Mapped[bool] = mapped_column(nullable=False, default=False)
    quality_status: Mapped[QualityStatus] = mapped_column(
        Enum(QualityStatus, name="quality_status"), nullable=False, default=QualityStatus.PENDING
    )
    raw_payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
