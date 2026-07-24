"""Integration test for reconcile_and_store -- requires a live database."""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models.company import Company
from src.database.models.market import MarketDataReconciliation, MarketPriceRaw
from src.database.models.ops import DataSourceRegistry
from src.database.session import make_engine
from src.ingestion.reconciliation import reconcile_and_store

pytestmark = pytest.mark.integration


@pytest.fixture()
def db_session():
    engine = make_engine("postgresql+psycopg://idx:idx@localhost:5433/idx_intelligence")
    with Session(engine) as session:
        yield session
        session.rollback()


@pytest.fixture()
def test_company_with_price(db_session):
    company = db_session.scalar(select(Company).where(Company.ticker == "ZZZR"))
    if company is None:
        company = Company(ticker="ZZZR", company_name="Test Fixture Company Reconcile")
        db_session.add(company)
        db_session.flush()

    source = db_session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == "fake_recon_source"))
    if source is None:
        source = DataSourceRegistry(name="fake_recon_source", category="market", access_type="fallback_provider", is_active=True)
        db_session.add(source)
        db_session.flush()

    trading_date = dt.date(2026, 6, 15)
    now = dt.datetime.now(dt.UTC)
    price_row = MarketPriceRaw(
        company_id=company.id,
        trade_date=trading_date,
        close=6500.0,
        source_id=source.id,
        retrieved_at=now,
        available_at=now,
        currency="IDR",
        unit="unit",
        verification_status="provider_reported",
    )
    db_session.add(price_row)
    db_session.commit()

    yield company, trading_date

    db_session.query(MarketDataReconciliation).filter(MarketDataReconciliation.company_id == company.id).delete()
    db_session.query(MarketPriceRaw).filter(MarketPriceRaw.company_id == company.id).delete()
    db_session.query(DataSourceRegistry).filter(DataSourceRegistry.name == "fake_recon_source").delete()
    db_session.query(Company).filter(Company.id == company.id).delete()
    db_session.commit()


def test_reconcile_and_store_updates_primary_row_status(db_session, test_company_with_price):
    company, trading_date = test_company_with_price

    reconcile_and_store(
        db_session,
        company_id=company.id,
        trading_date=trading_date,
        primary_provider="fake_recon_source",
        verification_provider="fake_verifier",
        primary_close=6500.0,
        verification_close=6500.0,
    )
    db_session.commit()

    recon = db_session.scalar(select(MarketDataReconciliation).where(MarketDataReconciliation.company_id == company.id))
    assert recon is not None
    assert recon.status == "matched"

    price_row = db_session.scalar(
        select(MarketPriceRaw).where(MarketPriceRaw.company_id == company.id, MarketPriceRaw.trade_date == trading_date)
    )
    assert price_row.verification_status == "reconciled_matched"


def test_reconcile_and_store_verification_unavailable_does_not_touch_price_row(db_session, test_company_with_price):
    company, trading_date = test_company_with_price

    reconcile_and_store(
        db_session,
        company_id=company.id,
        trading_date=trading_date,
        primary_provider="fake_recon_source",
        verification_provider="fake_verifier",
        primary_close=6500.0,
        verification_close=None,
    )
    db_session.commit()

    recon = db_session.scalar(select(MarketDataReconciliation).where(MarketDataReconciliation.company_id == company.id))
    assert recon.status == "verification_unavailable"

    price_row = db_session.scalar(
        select(MarketPriceRaw).where(MarketPriceRaw.company_id == company.id, MarketPriceRaw.trade_date == trading_date)
    )
    assert price_row.verification_status == "provider_reported"  # unchanged
