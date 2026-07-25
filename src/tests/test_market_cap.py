"""Integration tests for market cap ranking -- requires a live database.

fetch_and_store_shares_outstanding hits the real Yahoo Finance API (no
mock) -- consistent with how this project has verified every other
external call live rather than trusting an assumed response shape.
"""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models.company import Company
from src.database.models.market import MarketPriceClean
from src.database.models.mixins import QualityStatus
from src.database.models.ops import DataSourceRegistry
from src.database.session import make_engine
from src.ingestion.market_cap import fetch_and_store_shares_outstanding, rank_companies_by_market_cap

pytestmark = pytest.mark.integration


@pytest.fixture()
def db_session():
    engine = make_engine("postgresql+psycopg://idx:idx@localhost:5433/idx_intelligence")
    with Session(engine) as session:
        yield session
        session.rollback()


def test_fetch_and_store_shares_outstanding_real_ticker(db_session):
    company = db_session.scalar(select(Company).where(Company.ticker == "BBCA"))
    if company is None:
        pytest.skip("BBCA not present in this database")
    original_shares = company.shares_outstanding

    outcome = fetch_and_store_shares_outstanding(db_session, "BBCA")
    db_session.commit()

    assert outcome.skipped_reason is None
    assert outcome.shares_outstanding is not None
    assert outcome.shares_outstanding > 0

    db_session.refresh(company)
    assert company.shares_outstanding == outcome.shares_outstanding

    company.shares_outstanding = original_shares  # restore
    db_session.commit()


def test_fetch_and_store_shares_outstanding_unknown_ticker(db_session):
    outcome = fetch_and_store_shares_outstanding(db_session, "NOPE")
    assert outcome.skipped_reason is not None


def test_rank_companies_by_market_cap_orders_descending(db_session):
    now = dt.datetime.now(dt.UTC)
    source = db_session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == "fake_mcap_source"))
    if source is None:
        source = DataSourceRegistry(name="fake_mcap_source", category="market", access_type="internal_derived", is_active=True)
        db_session.add(source)
        db_session.flush()

    companies = []
    for ticker, shares, close in [("ZZZM1", 1000, 100.0), ("ZZZM2", 1000, 500.0), ("ZZZM3", 1000, 10.0)]:
        c = Company(ticker=ticker, company_name=f"Test {ticker}", shares_outstanding=shares)
        db_session.add(c)
        db_session.flush()
        db_session.add(
            MarketPriceClean(
                company_id=c.id,
                trade_date=dt.date(2026, 1, 1),
                close=close,
                source_id=source.id,
                retrieved_at=now,
                available_at=now,
                currency="IDR",
                unit="unit",
                quality_status=QualityStatus.VALID,
            )
        )
        companies.append(c)
    db_session.commit()

    try:
        # top_n must comfortably exceed the real company count (~950) --
        # otherwise these Rp-thousands test fixtures never appear in the
        # slice at all once real IDX companies (worth trillions) are in
        # the same database, and this becomes a false failure rather than
        # a real one.
        ranked = rank_companies_by_market_cap(db_session, 10_000)
        our_tickers_in_order = [r.ticker for r in ranked if r.ticker.startswith("ZZZM")]
        assert our_tickers_in_order == ["ZZZM2", "ZZZM1", "ZZZM3"]  # 500k > 100k > 10k market cap
    finally:
        for c in companies:
            db_session.query(MarketPriceClean).filter(MarketPriceClean.company_id == c.id).delete()
            db_session.query(Company).filter(Company.id == c.id).delete()
        db_session.query(DataSourceRegistry).filter(DataSourceRegistry.name == "fake_mcap_source").delete()
        db_session.commit()


def test_rank_companies_by_market_cap_falls_back_when_latest_bar_has_null_close(db_session):
    """Regression test: a first attempt at this ranking silently dropped
    BBCA/BBRI/BMRI/ASII (Indonesia's actual largest caps) because their
    most recently ingested row was today's still-forming bar with
    close=NULL, and the old query only ever looked at the single
    latest-dated row."""
    now = dt.datetime.now(dt.UTC)
    source = db_session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == "fake_mcap_source2"))
    if source is None:
        source = DataSourceRegistry(name="fake_mcap_source2", category="market", access_type="internal_derived", is_active=True)
        db_session.add(source)
        db_session.flush()

    company = Company(ticker="ZZZM4", company_name="Test ZZZM4 Mega Cap", shares_outstanding=1_000_000)
    db_session.add(company)
    db_session.flush()
    # Yesterday: a real close. Today: still-forming bar, close=NULL.
    db_session.add_all(
        [
            MarketPriceClean(
                company_id=company.id, trade_date=dt.date(2026, 1, 1), close=1000.0,
                source_id=source.id, retrieved_at=now, available_at=now,
                currency="IDR", unit="unit", quality_status=QualityStatus.VALID,
            ),
            MarketPriceClean(
                company_id=company.id, trade_date=dt.date(2026, 1, 2), close=None,
                source_id=source.id, retrieved_at=now, available_at=now,
                currency="IDR", unit="unit", quality_status=QualityStatus.VALID,
            ),
        ]
    )
    db_session.commit()

    try:
        ranked = rank_companies_by_market_cap(db_session, 10_000)  # see note above: must exceed real company count
        matches = [r for r in ranked if r.ticker == "ZZZM4"]
        assert len(matches) == 1  # must NOT be silently dropped
        assert matches[0].latest_close == 1000.0  # falls back to the last real close
        assert matches[0].price_date == dt.date(2026, 1, 1)
    finally:
        db_session.query(MarketPriceClean).filter(MarketPriceClean.company_id == company.id).delete()
        db_session.query(Company).filter(Company.id == company.id).delete()
        db_session.query(DataSourceRegistry).filter(DataSourceRegistry.name == "fake_mcap_source2").delete()
        db_session.commit()
