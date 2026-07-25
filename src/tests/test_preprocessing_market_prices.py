"""Integration tests for market_prices_raw -> market_prices_clean -- requires a live database."""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models.company import Company
from src.database.models.market import MarketPriceClean, MarketPriceRaw
from src.database.models.mixins import QualityStatus
from src.database.models.ops import DataSourceRegistry
from src.database.session import make_engine
from src.preprocessing.market_prices import build_clean_prices

pytestmark = pytest.mark.integration


@pytest.fixture()
def db_session():
    engine = make_engine("postgresql+psycopg://idx:idx@localhost:5433/idx_intelligence")
    with Session(engine) as session:
        yield session
        session.rollback()


@pytest.fixture()
def company_with_raw_prices(db_session):
    company = db_session.scalar(select(Company).where(Company.ticker == "ZZZP"))
    if company is None:
        company = Company(ticker="ZZZP", company_name="Test Fixture Company Preprocessing")
        db_session.add(company)
        db_session.flush()

    source = db_session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == "fake_preprocess_source"))
    if source is None:
        source = DataSourceRegistry(name="fake_preprocess_source", category="market", access_type="fallback_provider", is_active=True)
        db_session.add(source)
        db_session.flush()

    now = dt.datetime.now(dt.UTC)
    bars = [
        # (date, close, adjusted_close)
        (dt.date(2026, 1, 5), 1000.0, 1000.0),
        (dt.date(2026, 1, 6), 1010.0, 1010.0),
        (dt.date(2026, 1, 7), 2500.0, 2500.0),  # >35% jump -- should be flagged as outlier
        (dt.date(2026, 1, 8), 1015.0, 1015.0),
    ]
    for d, close, adj_close in bars:
        db_session.add(
            MarketPriceRaw(
                company_id=company.id,
                trade_date=d,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=1000,
                adjusted_close_provider=adj_close,
                source_id=source.id,
                retrieved_at=now,
                available_at=now,
                currency="IDR",
                unit="unit",
                quality_status=QualityStatus.VALID,
            )
        )
    db_session.commit()

    yield company

    db_session.query(MarketPriceClean).filter(MarketPriceClean.company_id == company.id).delete()
    db_session.query(MarketPriceRaw).filter(MarketPriceRaw.company_id == company.id).delete()
    db_session.query(DataSourceRegistry).filter(DataSourceRegistry.name == "fake_preprocess_source").delete()
    db_session.query(Company).filter(Company.id == company.id).delete()
    db_session.commit()


def test_build_clean_prices_writes_all_rows_and_flags_outlier(db_session, company_with_raw_prices):
    company = company_with_raw_prices
    outcome = build_clean_prices(db_session, "ZZZP", price_policy="provider_split_adjusted")
    db_session.commit()

    assert outcome.rows_written == 4
    # Both the spike (1010 -> 2500, +147%) AND the reversion (2500 -> 1015,
    # -59%) are >35% day-over-day moves -- correctly flagged independently,
    # since the check is symmetric day-over-day % change, not "vs. some
    # baseline."
    assert outcome.outliers_flagged == 2

    rows = db_session.scalars(
        select(MarketPriceClean).where(MarketPriceClean.company_id == company.id).order_by(MarketPriceClean.trade_date)
    ).all()
    assert len(rows) == 4
    assert rows[0].is_outlier_flagged is False
    assert rows[1].is_outlier_flagged is False
    assert rows[2].is_outlier_flagged is True  # the spike
    assert rows[3].is_outlier_flagged is True  # the reversion


def test_build_clean_prices_uses_provider_adjusted_close(db_session, company_with_raw_prices):
    build_clean_prices(db_session, "ZZZP", price_policy="provider_split_adjusted")
    db_session.commit()

    row = db_session.scalar(
        select(MarketPriceClean).where(
            MarketPriceClean.company_id == company_with_raw_prices.id, MarketPriceClean.trade_date == dt.date(2026, 1, 5)
        )
    )
    assert float(row.adjusted_close) == 1000.0
    assert float(row.adjustment_factor) == pytest.approx(1.0)


def test_build_clean_prices_raw_policy_ignores_adjusted_value(db_session, company_with_raw_prices):
    build_clean_prices(db_session, "ZZZP", price_policy="raw")
    db_session.commit()

    row = db_session.scalar(
        select(MarketPriceClean).where(
            MarketPriceClean.company_id == company_with_raw_prices.id, MarketPriceClean.trade_date == dt.date(2026, 1, 5)
        )
    )
    assert float(row.adjusted_close) == float(row.close)


def test_build_clean_prices_is_idempotent(db_session, company_with_raw_prices):
    build_clean_prices(db_session, "ZZZP", price_policy="provider_split_adjusted")
    db_session.commit()
    build_clean_prices(db_session, "ZZZP", price_policy="provider_split_adjusted")
    db_session.commit()

    rows = db_session.scalars(
        select(MarketPriceClean).where(MarketPriceClean.company_id == company_with_raw_prices.id)
    ).all()
    assert len(rows) == 4  # no duplicates


def test_build_clean_prices_skips_unknown_ticker(db_session):
    outcome = build_clean_prices(db_session, "NOPE", price_policy="raw")
    assert outcome.skipped_reason is not None


def test_build_clean_prices_skips_ticker_with_no_raw_data(db_session):
    company = Company(ticker="ZZZQ", company_name="No Data Yet")
    db_session.add(company)
    db_session.commit()
    try:
        outcome = build_clean_prices(db_session, "ZZZQ", price_policy="raw")
        assert outcome.skipped_reason is not None
        assert "backfill" in outcome.skipped_reason
    finally:
        db_session.query(Company).filter(Company.id == company.id).delete()
        db_session.commit()
