"""Integration tests for emiten metadata sync -- requires a live database.

Run with: docker compose up -d db && pytest -m integration
"""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.data_sources.base import (
    AccessType,
    ProviderUnavailableError,
    SourceDescriptor,
    SourcedValue,
    ValidationStatus,
)
from src.data_sources.market.base import CompanyRecord, MarketDataProvider
from src.database.models.company import Company
from src.database.session import make_engine
from src.ingestion.company_sync import sync_companies

pytestmark = pytest.mark.integration

_EQUITY_TICKERS = ["ZZZA", "ZZZB"]
_TEST_TICKERS = [*_EQUITY_TICKERS, "ZZZIDX"]


class _FakeProvider(MarketDataProvider):
    def __init__(self, records: list[CompanyRecord] | None = None, fail: bool = False):
        self._records = records if records is not None else []
        self._fail = fail

    @property
    def provider_name(self) -> str:
        return "fake_company_provider"

    def list_active_tickers(self):
        raise NotImplementedError

    def list_companies(self) -> SourcedValue[list[CompanyRecord]]:
        if self._fail:
            raise ProviderUnavailableError("simulated outage")
        now = dt.datetime.now(dt.UTC)
        return SourcedValue(
            value=self._records,
            source=SourceDescriptor(name="fake_company_provider", url="https://example.invalid", access_type=AccessType.FALLBACK_PROVIDER),
            retrieved_at=now,
            available_at=now,
            period_start=None,
            period_end=None,
            validation_status=ValidationStatus.VALID if self._records else ValidationStatus.INSUFFICIENT,
        )

    def get_ohlcv(self, ticker, start, end):
        raise NotImplementedError

    def get_corporate_actions(self, ticker, start, end):
        raise NotImplementedError


@pytest.fixture()
def db_session():
    engine = make_engine("postgresql+psycopg://idx:idx@localhost:5433/idx_intelligence")
    with Session(engine) as session:
        yield session
        session.rollback()
        for ticker in _TEST_TICKERS:
            session.query(Company).filter(Company.ticker == ticker).delete()
        session.commit()


def test_sync_creates_new_companies(db_session):
    provider = _FakeProvider([CompanyRecord("ZZZA", "Test Company A"), CompanyRecord("ZZZB", "Test Company B")])
    outcome = sync_companies(db_session, provider)
    db_session.commit()

    assert outcome.companies_created == 2
    assert outcome.skipped_reason is None

    rows = db_session.scalars(select(Company).where(Company.ticker.in_(_TEST_TICKERS))).all()
    assert {r.ticker for r in rows} == set(_EQUITY_TICKERS)
    assert all(r.asset_type == "equity" for r in rows)


def test_sync_infers_index_asset_type_from_provider_name(db_session):
    provider = _FakeProvider([CompanyRecord("ZZZIDX", "Test Benchmark Index")])
    outcome = sync_companies(db_session, provider)
    db_session.commit()

    company = db_session.scalar(select(Company).where(Company.ticker == "ZZZIDX"))
    assert outcome.companies_created == 1
    assert company is not None
    assert company.asset_type == "index"


def test_sync_updates_existing_company_name_without_deleting_others(db_session):
    db_session.add(Company(ticker="ZZZA", company_name="Old Name"))
    db_session.commit()

    provider = _FakeProvider([CompanyRecord("ZZZA", "New Name")])  # ZZZB not mentioned at all
    outcome = sync_companies(db_session, provider)
    db_session.commit()

    assert outcome.companies_updated == 1
    updated = db_session.scalar(select(Company).where(Company.ticker == "ZZZA"))
    assert updated.company_name == "New Name"


def test_sync_never_deletes_a_company_missing_from_the_provider_response(db_session):
    db_session.add(Company(ticker="ZZZA", company_name="Still Listed"))
    db_session.commit()

    provider = _FakeProvider([])  # provider returns nothing this run
    outcome = sync_companies(db_session, provider)
    db_session.commit()

    assert outcome.skipped_reason is not None  # empty result is treated as insufficient, not "delist everyone"
    still_there = db_session.scalar(select(Company).where(Company.ticker == "ZZZA"))
    assert still_there is not None


def test_sync_skips_on_provider_unavailable(db_session):
    provider = _FakeProvider(fail=True)
    outcome = sync_companies(db_session, provider)
    assert outcome.skipped_reason is not None
    assert "unavailable" in outcome.skipped_reason
