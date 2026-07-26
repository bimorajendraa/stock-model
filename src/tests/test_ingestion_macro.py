"""Integration tests for macro/industry ingestion -- requires a live
database. Uses a fake provider (distinct source name from the real
``yahoo_finance_macro``) so cleanup can safely delete everything under
that source without any risk of colliding with real production data in
the same tables (same lesson as
``test_ingestion_fundamentals.py``'s module docstring, applied
preemptively here since ``macro_series``/``industry_series`` rows aren't
scoped by company_id the way that incident was).
"""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.data_sources.base import AccessType, SourceDescriptor, SourcedValue, ValidationStatus
from src.data_sources.macro.base import MacroDataProvider, SeriesPoint
from src.database.models.macro import IndustrySeries, MacroSeries
from src.database.models.ops import DataSourceRegistry
from src.database.session import make_engine
from src.ingestion.macro import ingest_macro_series

pytestmark = pytest.mark.integration

_FAKE_SOURCE_NAME = "fake_macro_test_source"


@pytest.fixture()
def db_session():
    engine = make_engine("postgresql+psycopg://idx:idx@localhost:5433/idx_intelligence")
    with Session(engine) as session:
        yield session
        session.rollback()


class _FakeMacroProvider(MacroDataProvider):
    def __init__(self, points_by_series: dict[str, list[SeriesPoint]]) -> None:
        self._points_by_series = points_by_series
        self._source = SourceDescriptor(name=_FAKE_SOURCE_NAME, url="https://example.invalid", access_type=AccessType.FALLBACK_PROVIDER)

    @property
    def provider_name(self) -> str:
        return "fake_macro"

    def supported_series(self) -> list[str]:
        return list(self._points_by_series)

    def get_series(self, series_code: str, start: dt.date, end: dt.date) -> SourcedValue[list[SeriesPoint]]:
        now = dt.datetime.now(dt.UTC)
        points = self._points_by_series.get(series_code, [])
        return SourcedValue(
            value=points,
            source=self._source,
            retrieved_at=now,
            available_at=now,
            period_start=start,
            period_end=end,
            validation_status=ValidationStatus.VALID if points else ValidationStatus.INSUFFICIENT,
        )


@pytest.fixture(autouse=True)
def _cleanup(db_session):
    yield
    source = db_session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == _FAKE_SOURCE_NAME))
    if source is not None:
        db_session.query(MacroSeries).filter(MacroSeries.source_id == source.id).delete()
        db_session.query(IndustrySeries).filter(IndustrySeries.source_id == source.id).delete()
        db_session.query(DataSourceRegistry).filter(DataSourceRegistry.id == source.id).delete()
    db_session.commit()


def test_ingest_macro_series_routes_to_macro_table(db_session):
    points = [SeriesPoint(dt.date(2026, 1, 1), 15000.0), SeriesPoint(dt.date(2026, 1, 2), 15050.0)]
    provider = _FakeMacroProvider({"usdidr_fx": points})

    outcome = ingest_macro_series(db_session, provider, "usdidr_fx", dt.date(2026, 1, 1), dt.date(2026, 1, 2))
    db_session.commit()

    assert outcome.skipped_reason is None
    assert outcome.table == "macro"
    assert outcome.points_written == 2

    source = db_session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == _FAKE_SOURCE_NAME))
    rows = db_session.scalars(select(MacroSeries).where(MacroSeries.source_id == source.id)).all()
    assert len(rows) == 2
    assert {float(r.value) for r in rows} == {15000.0, 15050.0}


def test_ingest_macro_series_routes_to_industry_table(db_session):
    points = [SeriesPoint(dt.date(2026, 1, 1), 6100.0)]
    provider = _FakeMacroProvider({"ihsg_composite": points})

    outcome = ingest_macro_series(db_session, provider, "ihsg_composite", dt.date(2026, 1, 1), dt.date(2026, 1, 1))
    db_session.commit()

    assert outcome.table == "industry"
    source = db_session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == _FAKE_SOURCE_NAME))
    rows = db_session.scalars(select(IndustrySeries).where(IndustrySeries.source_id == source.id)).all()
    assert len(rows) == 1
    assert float(rows[0].value) == 6100.0


def test_ingest_macro_series_is_idempotent_on_rerun(db_session):
    points = [SeriesPoint(dt.date(2026, 1, 1), 15000.0)]
    provider = _FakeMacroProvider({"usdidr_fx": points})

    ingest_macro_series(db_session, provider, "usdidr_fx", dt.date(2026, 1, 1), dt.date(2026, 1, 1))
    db_session.commit()
    ingest_macro_series(db_session, provider, "usdidr_fx", dt.date(2026, 1, 1), dt.date(2026, 1, 1))
    db_session.commit()

    source = db_session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == _FAKE_SOURCE_NAME))
    rows = db_session.scalars(select(MacroSeries).where(MacroSeries.source_id == source.id)).all()
    assert len(rows) == 1  # ON CONFLICT upsert, not a duplicate row


def test_ingest_macro_series_upserts_updated_value(db_session):
    provider_v1 = _FakeMacroProvider({"usdidr_fx": [SeriesPoint(dt.date(2026, 1, 1), 15000.0)]})
    ingest_macro_series(db_session, provider_v1, "usdidr_fx", dt.date(2026, 1, 1), dt.date(2026, 1, 1))
    db_session.commit()

    provider_v2 = _FakeMacroProvider({"usdidr_fx": [SeriesPoint(dt.date(2026, 1, 1), 15123.0)]})
    ingest_macro_series(db_session, provider_v2, "usdidr_fx", dt.date(2026, 1, 1), dt.date(2026, 1, 1))
    db_session.commit()

    source = db_session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == _FAKE_SOURCE_NAME))
    row = db_session.scalar(select(MacroSeries).where(MacroSeries.source_id == source.id))
    assert float(row.value) == 15123.0  # updated in place, not a stale duplicate


def test_ingest_macro_series_unknown_series_code_is_skipped(db_session):
    provider = _FakeMacroProvider({})
    outcome = ingest_macro_series(db_session, provider, "not_a_real_series", dt.date(2026, 1, 1), dt.date(2026, 1, 1))
    assert outcome.skipped_reason is not None
    assert outcome.points_written == 0


def test_ingest_macro_series_uses_per_point_available_at_when_set(db_session):
    # A provider that can determine a real per-point available_at (e.g.
    # BPS) must have that honored, not overwritten by the batch-level
    # "now" -- see SeriesPoint's docstring on why the batch fallback is
    # wrong for historical backfill.
    real_available_at = dt.datetime(2016, 3, 15, tzinfo=dt.UTC)
    points = [SeriesPoint(dt.date(2016, 2, 29), 0.5, available_at=real_available_at)]
    provider = _FakeMacroProvider({"usdidr_fx": points})

    ingest_macro_series(db_session, provider, "usdidr_fx", dt.date(2016, 1, 1), dt.date(2016, 12, 31))
    db_session.commit()

    source = db_session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == _FAKE_SOURCE_NAME))
    row = db_session.scalar(select(MacroSeries).where(MacroSeries.source_id == source.id))
    assert row.available_at == real_available_at  # not "now" (the batch-level SourcedValue.available_at)


def test_ingest_macro_series_falls_back_to_batch_available_at_when_point_unset(db_session):
    # A provider that can't determine per-point availability (e.g. the
    # existing Yahoo Finance FX/index adapter before this fix, or any
    # future simple provider) must still work via the batch-level value.
    points = [SeriesPoint(dt.date(2026, 1, 1), 15000.0)]  # available_at left as default None
    provider = _FakeMacroProvider({"usdidr_fx": points})

    ingest_macro_series(db_session, provider, "usdidr_fx", dt.date(2026, 1, 1), dt.date(2026, 1, 1))
    db_session.commit()

    source = db_session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == _FAKE_SOURCE_NAME))
    row = db_session.scalar(select(MacroSeries).where(MacroSeries.source_id == source.id))
    assert row.available_at is not None
