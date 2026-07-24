"""Integration tests for market-data ingestion -- requires a live database.

Run with: docker compose up -d db && pytest -m integration
These are skipped by default (see pyproject.toml's default testpaths/markers
usage) unless explicitly selected, since they need real Postgres, not a
mock -- the point is proving the upsert/lineage/FK behavior actually works
against the schema from migrations/versions/, not just that the ORM calls
compile.
"""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.data_sources.base import (
    AccessType,
    SourceDescriptor,
    SourcedValue,
    ValidationStatus,
)
from src.data_sources.market.base import MarketDataProvider, OHLCVBar
from src.database.models.company import Company
from src.database.models.market import MarketPriceRaw
from src.database.models.ops import DataSourceRegistry
from src.database.session import make_engine
from src.ingestion.market_data import ingest_ohlcv

pytestmark = pytest.mark.integration


class _FakeProvider(MarketDataProvider):
    def __init__(self, bars: list[OHLCVBar]):
        self._bars = bars

    @property
    def provider_name(self) -> str:
        return "fake_test_provider"

    def list_active_tickers(self):
        raise NotImplementedError

    def list_companies(self):
        raise NotImplementedError

    def get_ohlcv(self, ticker, start, end):
        now = dt.datetime.now(dt.UTC)
        return SourcedValue(
            value=self._bars,
            source=SourceDescriptor(name="fake_test_provider", url="https://example.invalid", access_type=AccessType.FALLBACK_PROVIDER),
            retrieved_at=now,
            available_at=now,
            period_start=start,
            period_end=end,
            validation_status=ValidationStatus.VALID,
        )

    def get_corporate_actions(self, ticker, start, end):
        raise NotImplementedError


@pytest.fixture()
def db_session():
    engine = make_engine("postgresql+psycopg://idx:idx@localhost:5433/idx_intelligence")
    with Session(engine) as session:
        yield session
        session.rollback()


@pytest.fixture()
def test_company(db_session):
    company = db_session.scalar(select(Company).where(Company.ticker == "ZZZZ"))
    if company is None:
        company = Company(ticker="ZZZZ", company_name="Test Fixture Company")
        db_session.add(company)
        db_session.flush()
    yield company
    db_session.query(MarketPriceRaw).filter(MarketPriceRaw.company_id == company.id).delete()
    db_session.query(DataSourceRegistry).filter(DataSourceRegistry.name == "fake_test_provider").delete()
    db_session.query(Company).filter(Company.id == company.id).delete()
    db_session.commit()


def test_ingest_ohlcv_writes_rows_with_lineage(db_session, test_company):
    bars = [
        OHLCVBar(dt.date(2026, 7, 1), 9000, 9050, 8950, 9010, 1000),
        OHLCVBar(dt.date(2026, 7, 2), 9010, 9100, 9000, 9080, 1500),
    ]
    provider = _FakeProvider(bars)

    outcome = ingest_ohlcv(db_session, provider, "ZZZZ", dt.date(2026, 7, 1), dt.date(2026, 7, 2))
    db_session.commit()

    assert outcome.records_written == 2
    assert outcome.skipped_reason is None

    rows = db_session.scalars(
        select(MarketPriceRaw).where(MarketPriceRaw.company_id == test_company.id).order_by(MarketPriceRaw.trade_date)
    ).all()
    assert len(rows) == 2
    assert float(rows[0].close) == 9010
    assert rows[0].source_id is not None
    assert rows[0].available_at is not None

    source = db_session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == "fake_test_provider"))
    assert source is not None
    assert source.category == "market"
    assert source.access_type == "fallback_provider"


def test_ingest_ohlcv_upsert_is_idempotent(db_session, test_company):
    bars = [OHLCVBar(dt.date(2026, 7, 1), 9000, 9050, 8950, 9010, 1000)]
    provider = _FakeProvider(bars)

    ingest_ohlcv(db_session, provider, "ZZZZ", dt.date(2026, 7, 1), dt.date(2026, 7, 1))
    db_session.commit()

    updated_bars = [OHLCVBar(dt.date(2026, 7, 1), 9000, 9050, 8950, 9500, 2000)]  # revised close/volume
    provider2 = _FakeProvider(updated_bars)
    ingest_ohlcv(db_session, provider2, "ZZZZ", dt.date(2026, 7, 1), dt.date(2026, 7, 1))
    db_session.commit()

    rows = db_session.scalars(
        select(MarketPriceRaw).where(MarketPriceRaw.company_id == test_company.id)
    ).all()
    assert len(rows) == 1  # no duplicate row -- upsert, not insert
    assert float(rows[0].close) == 9500
    assert rows[0].volume == 2000


def test_ingest_ohlcv_skips_unknown_ticker(db_session):
    provider = _FakeProvider([])
    outcome = ingest_ohlcv(db_session, provider, "NOPE", dt.date(2026, 7, 1), dt.date(2026, 7, 1))
    assert outcome.skipped_reason is not None
    assert "Company" in outcome.skipped_reason
