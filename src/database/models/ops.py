"""Operational tables: provider registry, pipeline runs, data quality, alerts
(spec §4-6, §30, §33).

``DataSourceRegistry`` is what every ``SourceLineageMixin.source_id`` points
at -- it exists before any fact table can be written to, which is why it's
defined first in the initial migration.

``DataSourceCapability`` (table ``data_sources``) is a separate, later
addition: a capability/health-check audit registry answering "is this
source actually reachable and returning real content right now," not
"which adapter wrote this fact row." Deliberately NOT merged into
``DataSourceRegistry`` -- that table is a lightweight FK target every fact
table across this project already points at (market/fundamentals/macro/
news/sector pipelines, ~10 modules), and it has no notion of a source
that's only a *candidate* (no adapter/ingestion code exists for it yet,
e.g. a source found live but not yet wired up) or of a health check that
can fail independently of any actual ingestion run. Linked to
``DataSourceRegistry`` only loosely, by matching ``source_code`` against
``DataSourceRegistry.name`` where an adapter already exists -- not a hard
FK, since a candidate source is auditable before any adapter exists.
"""
from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
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


class SourceType(str, enum.Enum):
    API = "api"
    HTML = "html"
    XLSX = "xlsx"
    CSV = "csv"
    ZIP = "zip"
    XBRL = "xbrl"
    XML = "xml"
    RSS = "rss"
    PDF = "pdf"
    DOCUMENT_REPOSITORY = "document_repository"


class AuthorityLevel(str, enum.Enum):
    REGULATOR = "regulator"
    EXCHANGE = "exchange"
    ISSUER = "issuer"
    GOVERNMENT = "government"
    INTERNATIONAL_INSTITUTION = "international_institution"
    NEWS_AGENCY = "news_agency"
    BUSINESS_MEDIA = "business_media"
    GENERAL_MEDIA = "general_media"
    AGGREGATOR = "aggregator"
    UNOFFICIAL_PROVIDER = "unofficial_provider"


class SourceUsageMode(str, enum.Enum):
    PRODUCTION_ALLOWED = "production_allowed"
    RESEARCH_ONLY = "research_only"
    METADATA_ONLY = "metadata_only"
    VERIFICATION_ONLY = "verification_only"
    LICENSE_REVIEW = "license_review"


class SourceHealthStatus(str, enum.Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    EMPTY = "empty"
    FORMAT_CHANGED = "format_changed"
    RATE_LIMITED = "rate_limited"
    AUTHENTICATION_REQUIRED = "authentication_required"
    UNVERIFIED = "unverified"


class DataSourceCapability(Base, TimestampMixin):
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    source_name: Mapped[str] = mapped_column(String(256), nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType, name="source_type"), nullable=False)
    data_category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # market | fundamentals | macro | industry | sector | news | discount_rate
    authority_level: Mapped[AuthorityLevel] = mapped_column(
        Enum(AuthorityLevel, name="authority_level"), nullable=False
    )
    usage_mode: Mapped[SourceUsageMode] = mapped_column(
        Enum(SourceUsageMode, name="source_usage_mode"), nullable=False
    )
    official_status: Mapped[str] = mapped_column(String(32), nullable=False)  # official | unofficial
    license_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    # public | review_required | restricted | unknown
    access_method: Mapped[str] = mapped_column(String(32), nullable=False)
    # http_get | api_key | rss | file_download | manual
    requires_api_key: Mapped[bool] = mapped_column(nullable=False, default=False)
    supports_history: Mapped[bool] = mapped_column(nullable=False, default=False)
    supports_incremental: Mapped[bool] = mapped_column(nullable=False, default=False)
    supports_commercial_use: Mapped[bool] = mapped_column(nullable=False, default=False)
    health_status: Mapped[SourceHealthStatus] = mapped_column(
        Enum(SourceHealthStatus, name="source_health_status"), nullable=False, default=SourceHealthStatus.UNVERIFIED
    )
    last_success_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_failure_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


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


class PipelineCompanyResult(Base, TimestampMixin):
    """One durable result for each company attempt inside a pipeline run.

    This is intentionally an append-only attempt log rather than a marker
    row in a fact table.  A provider returning no data is operationally
    different from a company that has never been tried, while neither case
    is valid fact data.  ``retry_after`` lets resumable batch commands avoid
    repeatedly calling a provider for the same known-empty ticker.
    """

    __tablename__ = "pipeline_company_results"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'no_data', 'failed')",
            name="ck_pipeline_company_results_status",
        ),
        Index(
            "ix_pipeline_company_results_pipeline_company",
            "pipeline_name",
            "company_id",
        ),
        Index(
            "ix_pipeline_company_results_pipeline_retry_after",
            "pipeline_name",
            "retry_after",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pipeline_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempted_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    retry_after: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)


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
