"""Integration tests for corporate action ingestion -- requires a live database."""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.data_sources.base import AccessType, SourceDescriptor, SourcedValue, ValidationStatus
from src.data_sources.market.base import MarketDataProvider
from src.database.models.company import Company
from src.database.models.market import CorporateAction
from src.database.models.ops import DataSourceRegistry
from src.database.session import make_engine
from src.ingestion.corporate_actions import ingest_corporate_actions

pytestmark = pytest.mark.integration


class _FakeProvider(MarketDataProvider):
    def __init__(self, name: str, actions: list[dict]):
        self._name = name
        self._actions = actions

    @property
    def provider_name(self) -> str:
        return self._name

    def list_active_tickers(self):
        raise NotImplementedError

    def list_companies(self):
        raise NotImplementedError

    def get_ohlcv(self, ticker, start, end):
        raise NotImplementedError

    def get_corporate_actions(self, ticker, start, end):
        now = dt.datetime.now(dt.UTC)
        return SourcedValue(
            value=self._actions,
            source=SourceDescriptor(name=self._name, url="https://example.invalid", access_type=AccessType.FALLBACK_PROVIDER),
            retrieved_at=now,
            available_at=now,
            period_start=start,
            period_end=end,
            validation_status=ValidationStatus.VALID,
        )


@pytest.fixture()
def db_session():
    engine = make_engine("postgresql+psycopg://idx:idx@localhost:5433/idx_intelligence")
    with Session(engine) as session:
        yield session
        session.rollback()


@pytest.fixture()
def test_company(db_session):
    company = db_session.scalar(select(Company).where(Company.ticker == "ZZZC"))
    if company is None:
        company = Company(ticker="ZZZC", company_name="Test Fixture Company CA")
        db_session.add(company)
        db_session.flush()
    yield company
    db_session.query(CorporateAction).filter(CorporateAction.company_id == company.id).delete()
    db_session.query(DataSourceRegistry).filter(DataSourceRegistry.name.in_(["fake_ca_a", "fake_ca_b"])).delete()
    db_session.query(Company).filter(Company.id == company.id).delete()
    db_session.commit()


def test_ingest_writes_action_with_provider_reported_status(db_session, test_company):
    provider = _FakeProvider("fake_ca_a", [{"action_type": "cash_dividend", "ex_date": "2026-06-01", "cash_amount": 50.0}])
    outcome = ingest_corporate_actions(db_session, provider, "ZZZC", dt.date(2026, 1, 1), dt.date(2026, 12, 31))
    db_session.commit()

    assert outcome.records_written == 1
    rows = db_session.scalars(select(CorporateAction).where(CorporateAction.company_id == test_company.id)).all()
    assert len(rows) == 1
    assert rows[0].verification_status == "provider_reported"
    assert float(rows[0].cash_amount) == 50.0


def test_ingest_same_source_rerun_updates_not_duplicates(db_session, test_company):
    provider = _FakeProvider("fake_ca_a", [{"action_type": "cash_dividend", "ex_date": "2026-06-01", "cash_amount": 50.0}])
    ingest_corporate_actions(db_session, provider, "ZZZC", dt.date(2026, 1, 1), dt.date(2026, 12, 31))
    db_session.commit()

    provider_revised = _FakeProvider(
        "fake_ca_a", [{"action_type": "cash_dividend", "ex_date": "2026-06-01", "cash_amount": 75.0}]
    )
    ingest_corporate_actions(db_session, provider_revised, "ZZZC", dt.date(2026, 1, 1), dt.date(2026, 12, 31))
    db_session.commit()

    rows = db_session.scalars(select(CorporateAction).where(CorporateAction.company_id == test_company.id)).all()
    assert len(rows) == 1  # updated in place, not duplicated
    assert float(rows[0].cash_amount) == 75.0


def test_ingest_different_sources_never_overwrite_each_other(db_session, test_company):
    provider_a = _FakeProvider("fake_ca_a", [{"action_type": "cash_dividend", "ex_date": "2026-06-01", "cash_amount": 50.0}])
    provider_b = _FakeProvider("fake_ca_b", [{"action_type": "cash_dividend", "ex_date": "2026-06-01", "cash_amount": 55.0}])

    ingest_corporate_actions(db_session, provider_a, "ZZZC", dt.date(2026, 1, 1), dt.date(2026, 12, 31))
    db_session.commit()
    ingest_corporate_actions(db_session, provider_b, "ZZZC", dt.date(2026, 1, 1), dt.date(2026, 12, 31))
    db_session.commit()

    rows = db_session.scalars(select(CorporateAction).where(CorporateAction.company_id == test_company.id)).all()
    assert len(rows) == 2  # conflicting reports from two sources both preserved
    amounts = {float(r.cash_amount) for r in rows}
    assert amounts == {50.0, 55.0}
