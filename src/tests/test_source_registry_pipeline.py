"""Integration tests for the source registry DB layer -- requires a live
database. ``sync_catalog``/``run_audit`` operate on the real, shared
``SOURCE_CATALOG`` (this is a support/registry table, not analytical fact
data -- auditing it for real is the intended behavior in every
environment, unlike e.g. news_sentiment where fixture pollution would
corrupt real analysis, so no disposable-fixture pattern is needed here).
"""
from __future__ import annotations

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.data_sources.registry import SOURCE_CATALOG, run_audit, sync_catalog
from src.database.models.ops import DataSourceCapability, SourceHealthStatus
from src.database.session import make_engine

pytestmark = pytest.mark.integration


@pytest.fixture()
def db_session():
    engine = make_engine("postgresql+psycopg://idx:idx@localhost:5433/idx_intelligence")
    with Session(engine) as session:
        yield session
        session.rollback()


class _FakeSettings:
    bps_api_key = None
    fred_api_key = None
    twelve_data_api_key = None


def test_sync_catalog_is_idempotent(db_session):
    written_first = sync_catalog(db_session)
    db_session.commit()
    written_second = sync_catalog(db_session)
    db_session.commit()

    assert written_first == len(SOURCE_CATALOG)
    assert written_second == len(SOURCE_CATALOG)

    rows = db_session.scalars(
        select(DataSourceCapability).where(DataSourceCapability.source_code == SOURCE_CATALOG[0].source_code)
    ).all()
    assert len(rows) == 1  # not duplicated across two syncs


@respx.mock
def test_run_audit_updates_health_status_and_respects_category_filter(db_session):
    sync_catalog(db_session)
    db_session.commit()

    macro_code = next(e.source_code for e in SOURCE_CATALOG if e.data_category == "macro")
    macro_row = db_session.scalar(select(DataSourceCapability).where(DataSourceCapability.source_code == macro_code))
    checked_at_before = macro_row.checked_at

    for entry in SOURCE_CATALOG:
        url = entry.probe_url or entry.base_url
        if "{api_key}" in url:
            continue
        respx.get(url).mock(return_value=httpx.Response(200, text="x" * 500))

    results = run_audit(db_session, _FakeSettings(), category="news")
    db_session.commit()

    news_codes = {e.source_code for e in SOURCE_CATALOG if e.data_category == "news"}
    assert {r[0] for r in results} == news_codes

    row = db_session.scalar(
        select(DataSourceCapability).where(DataSourceCapability.source_code == next(iter(news_codes)))
    )
    assert row.health_status in (SourceHealthStatus.HEALTHY, SourceHealthStatus.FORMAT_CHANGED)
    assert row.checked_at is not None

    db_session.refresh(macro_row)
    assert macro_row.checked_at == checked_at_before  # untouched by a news-only audit
