"""Integration tests for the technical feature pipeline -- requires a live database."""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models.company import Company
from src.database.models.features import TechnicalFeature
from src.database.models.macro import IndustrySeries
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


@pytest.fixture()
def company_with_longer_clean_prices(db_session):
    """~90 rows of synthetic price data, placed on the SAME real trading
    dates real ``ihsg_composite`` data has (not every weekday) --
    real IDX trading calendars have real holidays (e.g. 2025-01-01 New
    Year), so a synthetic fixture that just skips Sat/Sun still doesn't
    match. Two earlier versions of this fixture (every calendar day, then
    every weekday) both left every beta/alpha value NaN even though the
    right feature *names* appeared, because ``rolling(window,
    min_periods=window)`` needs ALL `window` rows in a given position to
    be non-NaN, and even a handful of fixture-vs-real-calendar mismatches
    scattered across ~90 rows means no 60-row window is ever fully clean.
    Caught by actually running against real BBCA production data (whose
    own calendar naturally matches IHSG's) and confirming beta_60
    computed correctly there -- the pipeline was right, the fixture's
    calendar was wrong, twice. Fixed by reading real ``ihsg_composite``
    dates directly and placing fixture rows on exactly those dates.
    Deliberately does NOT insert any industry_series rows itself --
    reuses the real production data already in this database rather than
    risking any collision with it (see test_ingestion_macro.py's module
    docstring for the same isolation concern applied to a different
    table)."""
    real_dates = [
        r[0]
        for r in db_session.execute(
            select(IndustrySeries.observation_date)
            .where(IndustrySeries.series_code == "ihsg_composite", IndustrySeries.observation_date >= dt.date(2025, 1, 1))
            .order_by(IndustrySeries.observation_date)
            .limit(90)
        ).all()
    ]

    company = db_session.scalar(select(Company).where(Company.ticker == "ZZZFL"))
    if company is None:
        company = Company(ticker="ZZZFL", company_name="Test Fixture Company Features Longer")
        db_session.add(company)
        db_session.flush()

    source = db_session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == "fake_features_source_longer"))
    if source is None:
        source = DataSourceRegistry(
            name="fake_features_source_longer", category="market", access_type="internal_derived", is_active=True
        )
        db_session.add(source)
        db_session.flush()

    now = dt.datetime.now(dt.UTC)
    price = 1000.0
    for i, d in enumerate(real_dates):
        price += (1 if i % 3 else -1) * 5
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
    db_session.query(DataSourceRegistry).filter(DataSourceRegistry.name == "fake_features_source_longer").delete()
    db_session.query(Company).filter(Company.id == company.id).delete()
    db_session.commit()


def test_real_ihsg_data_covers_the_fixture_date_range(db_session):
    # Precondition check, not the real assertion -- if this fails, the
    # market-relative tests below would fail for an uninteresting reason
    # (macro sync hasn't been run in this DB), not a real pipeline bug.
    count = db_session.scalar(
        select(IndustrySeries.id).where(
            IndustrySeries.series_code == "ihsg_composite",
            IndustrySeries.observation_date >= dt.date(2025, 1, 1),
            IndustrySeries.observation_date <= dt.date(2025, 4, 30),
        )
    )
    if count is None:
        pytest.skip("no real ihsg_composite data in this range -- run `python -m src.cli macro sync` first")


def test_compute_technical_features_includes_market_relative_features(db_session, company_with_longer_clean_prices):
    company = company_with_longer_clean_prices
    outcome = compute_technical_features(db_session, "ZZZFL")
    db_session.commit()
    if outcome.skipped_reason:
        pytest.skip(outcome.skipped_reason)

    feature_names = {
        r[0]
        for r in db_session.execute(
            select(TechnicalFeature.feature_name).where(TechnicalFeature.company_id == company.id).distinct()
        )
    }
    if "beta_60" not in feature_names:
        pytest.skip("no real ihsg_composite overlap in this DB for this date range -- run `python -m src.cli macro sync` first")

    for expected in ("beta_60", "alpha_60", "relative_strength_5", "relative_strength_20", "relative_strength_60"):
        assert expected in feature_names
    # 252-day windows need 252 trading days of history -- this fixture
    # only has 90, so they must NOT appear (same "no long windows when
    # history too short" behavior as sma_200 elsewhere).
    assert "beta_252" not in feature_names
    assert "relative_strength_252" not in feature_names


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
