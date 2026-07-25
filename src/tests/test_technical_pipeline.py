"""Integration tests for the technical feature pipeline -- requires a live database."""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models.company import Company
from src.database.models.features import TechnicalFeature
from src.database.models.market import MarketPriceClean
from src.database.models.mixins import QualityStatus
from src.database.models.ops import DataSourceRegistry
from src.database.session import make_engine
from src.features.technical.pipeline import compute_technical_features

pytestmark = pytest.mark.integration


@pytest.fixture()
def db_session():
    engine = make_engine("postgresql+psycopg://idx:idx@localhost:5433/idx_intelligence")
    with Session(engine) as session:
        yield session
        session.rollback()


@pytest.fixture()
def company_with_clean_prices(db_session):
    company = db_session.scalar(select(Company).where(Company.ticker == "ZZZF"))
    if company is None:
        company = Company(ticker="ZZZF", company_name="Test Fixture Company Features")
        db_session.add(company)
        db_session.flush()

    source = db_session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == "fake_features_source"))
    if source is None:
        source = DataSourceRegistry(name="fake_features_source", category="market", access_type="internal_derived", is_active=True)
        db_session.add(source)
        db_session.flush()

    now = dt.datetime.now(dt.UTC)
    start = dt.date(2025, 1, 1)
    price = 1000.0
    for i in range(60):  # enough for the shorter-window indicators to populate
        d = start + dt.timedelta(days=i)
        price += (1 if i % 3 else -1) * 5  # small deterministic wiggle, never zero/negative
        db_session.add(
            MarketPriceClean(
                company_id=company.id,
                trade_date=d,
                open=price,
                high=price + 5,
                low=price - 5,
                close=price,
                adjusted_close=price,
                volume=10000 + i * 10,
                adjustment_factor=1.0,
                is_outlier_flagged=False,
                is_missing_trading_day_filled=False,
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

    db_session.query(TechnicalFeature).filter(TechnicalFeature.company_id == company.id).delete()
    db_session.query(MarketPriceClean).filter(MarketPriceClean.company_id == company.id).delete()
    db_session.query(DataSourceRegistry).filter(DataSourceRegistry.name == "fake_features_source").delete()
    db_session.query(Company).filter(Company.id == company.id).delete()
    db_session.commit()


def test_compute_technical_features_writes_expected_feature_names(db_session, company_with_clean_prices):
    company = company_with_clean_prices
    outcome = compute_technical_features(db_session, "ZZZF")
    db_session.commit()

    assert outcome.dates_processed == 60
    assert outcome.rows_written > 0
    assert outcome.skipped_reason is None

    feature_names = {
        r[0]
        for r in db_session.execute(
            select(TechnicalFeature.feature_name).where(TechnicalFeature.company_id == company.id).distinct()
        )
    }
    for expected in ("sma_5", "sma_20", "rsi_14", "macd", "bb_upper_20", "atr_14", "obv"):
        assert expected in feature_names


def test_compute_technical_features_is_idempotent(db_session, company_with_clean_prices):
    compute_technical_features(db_session, "ZZZF")
    db_session.commit()
    count_first = db_session.scalar(
        select(TechnicalFeature).where(TechnicalFeature.company_id == company_with_clean_prices.id)
    )
    rows_first = list(
        db_session.scalars(select(TechnicalFeature).where(TechnicalFeature.company_id == company_with_clean_prices.id))
    )

    compute_technical_features(db_session, "ZZZF")
    db_session.commit()
    rows_second = list(
        db_session.scalars(select(TechnicalFeature).where(TechnicalFeature.company_id == company_with_clean_prices.id))
    )

    assert len(rows_first) == len(rows_second)  # no duplicate accumulation on re-run
    del count_first


def test_compute_technical_features_no_long_windows_when_history_too_short(db_session, company_with_clean_prices):
    # Only 60 days of history -- sma_200 (needs 200) should never appear.
    compute_technical_features(db_session, "ZZZF")
    db_session.commit()
    has_sma_200 = db_session.scalar(
        select(TechnicalFeature).where(
            TechnicalFeature.company_id == company_with_clean_prices.id, TechnicalFeature.feature_name == "sma_200"
        )
    )
    assert has_sma_200 is None


def test_compute_technical_features_skips_unknown_ticker(db_session):
    outcome = compute_technical_features(db_session, "NOPE")
    assert outcome.skipped_reason is not None


def test_compute_technical_features_skips_ticker_with_no_clean_data(db_session):
    company = Company(ticker="ZZZG", company_name="No Clean Data Yet")
    db_session.add(company)
    db_session.commit()
    try:
        outcome = compute_technical_features(db_session, "ZZZG")
        assert outcome.skipped_reason is not None
        assert "build-clean" in outcome.skipped_reason
    finally:
        db_session.query(Company).filter(Company.id == company.id).delete()
        db_session.commit()
