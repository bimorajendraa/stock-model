"""Macro/industry ingestion: provider adapter -> ``macro_series`` or
``industry_series`` (spec section 3.4), routed per
``src/data_sources/macro/taxonomy.py``'s ``SERIES_CATALOG``.

Unlike the fundamentals/technical-features tables, both destination
tables already have a real unique constraint
(``series_code``, ``observation_date``, ``source_id``) from the Tahap 1
schema -- idempotency here is a genuine ``ON CONFLICT`` upsert, not a
clear-then-rewrite.
"""
from __future__ import annotations

import dataclasses
import datetime as dt

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.data_sources.base import ProviderUnavailableError, SourceDescriptor
from src.data_sources.macro.base import MacroDataProvider
from src.data_sources.macro.taxonomy import SERIES_CATALOG
from src.database.models.macro import IndustrySeries, MacroSeries
from src.database.models.mixins import QualityStatus
from src.database.models.ops import DataSourceRegistry
from src.ingestion.resilience import with_retry

_TABLE_MODELS = {"macro": MacroSeries, "industry": IndustrySeries}
_TABLE_CONSTRAINTS = {"macro": "uq_macro_series_obs", "industry": "uq_industry_series_obs"}


@dataclasses.dataclass
class MacroIngestOutcome:
    series_code: str
    table: str | None = None
    points_fetched: int = 0
    points_written: int = 0
    skipped_reason: str | None = None


def _get_or_create_source(session: Session, descriptor: SourceDescriptor, category: str) -> DataSourceRegistry:
    source = session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == descriptor.name))
    if source is not None:
        return source
    source = DataSourceRegistry(
        name=descriptor.name,
        category=category,
        access_type=descriptor.access_type.value,
        base_url=descriptor.url,
        is_active=True,
    )
    session.add(source)
    session.flush()
    return source


def ingest_macro_series(
    session: Session,
    provider: MacroDataProvider,
    series_code: str,
    start: dt.date,
    end: dt.date,
    max_retries: int = 4,
) -> MacroIngestOutcome:
    outcome = MacroIngestOutcome(series_code=series_code)

    definition = SERIES_CATALOG.get(series_code)
    if definition is None:
        outcome.skipped_reason = f"unknown series_code {series_code!r} -- not in SERIES_CATALOG"
        return outcome
    outcome.table = definition.table

    try:
        fetch = with_retry(max_retries)(provider.get_series)
        result = fetch(series_code, start, end)
    except ProviderUnavailableError as exc:
        outcome.skipped_reason = f"provider unavailable: {exc}"
        return outcome

    if not result.is_usable():
        outcome.skipped_reason = f"provider returned no usable data (status={result.validation_status.value})"
        return outcome

    points = result.value
    outcome.points_fetched = len(points)
    if not points:
        return outcome

    source = _get_or_create_source(session, result.source, category="macro")
    model = _TABLE_MODELS[definition.table]
    constraint = _TABLE_CONSTRAINTS[definition.table]

    rows = [
        {
            "series_code": series_code,
            "series_name": definition.series_name,
            "observation_date": point.observation_date,
            "value": point.value,
            "unit_of_measure": definition.unit_of_measure,
            "source_id": source.id,
            "retrieved_at": result.retrieved_at,
            # per-point available_at when the provider can determine one
            # (e.g. BPS: real publication-lag estimate); the batch-level
            # value is only point-in-time-correct for same-day data, not
            # a multi-year backfill -- see SeriesPoint's docstring.
            "available_at": point.available_at if point.available_at is not None else result.available_at,
            "period_start": point.observation_date,
            "period_end": point.observation_date,
            # currency is a required SourceLineageMixin field, but most of
            # these series aren't currency-denominated at all (index
            # points, a yield percentage) -- the real semantics live in
            # unit_of_measure/unit; currency stays the platform default
            # rather than a fabricated-looking per-series guess.
            "currency": "IDR",
            "unit": definition.unit_of_measure,
            "is_restated": False,
            "quality_status": QualityStatus.VALID,
        }
        for point in points
    ]

    stmt = insert(model).values(rows)
    update_cols = {"value": stmt.excluded.value, "retrieved_at": stmt.excluded.retrieved_at, "available_at": stmt.excluded.available_at}
    stmt = stmt.on_conflict_do_update(constraint=constraint, set_=update_cols)
    session.execute(stmt)

    outcome.points_written = len(rows)
    return outcome
