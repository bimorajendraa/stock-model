"""Operational tables: provider registry, pipeline runs, data quality, alerts
(spec §4-6, §30, §33).

``DataSourceRegistry`` is what every ``SourceLineageMixin.source_id`` points
at -- it exists before any fact table can be written to, which is why it's
defined first in the initial migration.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base
from src.database.models.mixins import TimestampMixin


class DataSourceRegistry(Base, TimestampMixin):
    __tablename__ = "data_source_registry"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    category: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    # market | fundamentals | macro | industry | news
    access_type: Mapped[str] = mapped_column(String(24), nullable=False)
    # official | documented_free | fallback_provider
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class PipelineRun(Base, TimestampMixin):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_uuid: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, unique=True)
    pipeline_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    # running | succeeded | failed | partial
    started_at: Mapped[dt.datetime] = mapped_column(nullable=False)
    completed_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    records_in: Mapped[int | None] = mapped_column(nullable=True)
    records_failed: Mapped[int | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class DataQualityResult(Base, TimestampMixin):
    __tablename__ = "data_quality_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_run_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    table_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    check_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # pass | warning | fail
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    checked_at: Mapped[dt.datetime] = mapped_column(nullable=False)


class Alert(Base, TimestampMixin):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)  # info | warning | critical
    message: Mapped[str] = mapped_column(Text, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")  # open | acknowledged | resolved
    resolved_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
