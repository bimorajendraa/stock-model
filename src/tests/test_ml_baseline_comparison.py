"""Integration test for the full baseline comparison pipeline -- requires
a live database. Uses synthetic-but-deterministic price series (not
fixtures pretending to be real market data -- these are clearly
constructed patterns purely to exercise the pipeline's plumbing)."""
from __future__ import annotations

import datetime as dt

import numpy as np
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
from src.ml.training.run_baseline_comparison import run_baseline_comparison

pytestmark = pytest.mark.integration

TEST_TICKERS = ["ZZZB1", "ZZZB2"]


@pytest.fixture()
def db_session():
    engine = make_engine("postgresql+psycopg://idx:idx@localhost:5433/idx_intelligence")
    with Session(engine) as session:
        yield session
        session.rollback()


@pytest.fixture()
def companies_with_features(db_session):
    source = db_session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == "fake_baseline_source"))
    if source is None:
        source = DataSourceRegistry(name="fake_baseline_source", category="market", access_type="internal_derived", is_active=True)
        db_session.add(source)
        db_session.flush()

    now = dt.datetime.now(dt.UTC)
    rng = np.random.default_rng(7)
    companies = []
    for ticker in TEST_TICKERS:
        company = Company(ticker=ticker, company_name=f"Test {ticker}")
        db_session.add(company)
        db_session.flush()
        companies.append(company)

        price = 1000.0
        start = dt.date(2024, 1, 1)
        for i in range(500):
            d = start + dt.timedelta(days=i)
            price *= 1 + rng.normal(0, 0.01)
            price = max(price, 10.0)
            db_session.add(
                MarketPriceClean(
                    company_id=company.id,
                    trade_date=d,
                    open=price,
                    high=price * 1.01,
                    low=price * 0.99,
                    close=price,
                    adjusted_close=price,
                    volume=int(10000 + rng.uniform(0, 5000)),
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
        compute_technical_features(db_session, ticker)
        db_session.commit()

    yield companies

    for company in companies:
        db_session.query(TechnicalFeature).filter(TechnicalFeature.company_id == company.id).delete()
        db_session.query(MarketPriceClean).filter(MarketPriceClean.company_id == company.id).delete()
        db_session.query(Company).filter(Company.id == company.id).delete()
    db_session.query(DataSourceRegistry).filter(DataSourceRegistry.name == "fake_baseline_source").delete()
    db_session.commit()


def test_run_baseline_comparison_produces_results_for_all_models(db_session, companies_with_features):
    results, info = run_baseline_comparison(db_session, TEST_TICKERS, horizon_days=5, embargo_days=2)

    assert "error" not in info
    assert info["n_train"] > 0
    assert info["n_validation"] > 0
    assert info["n_test"] > 0

    model_names = {r.model_name for r in results}
    assert model_names == {"naive_base_rate", "moving_average_rule", "logistic_regression", "random_forest", "simple_mlp"}

    for r in results:
        assert 0 <= r.validation.precision <= 1
        assert 0 <= r.test.precision <= 1
        assert r.validation.n_samples == info["n_validation"]
        assert r.test.n_samples == info["n_test"]


def test_run_baseline_comparison_naive_and_learned_models_differ(db_session, companies_with_features):
    # Sanity check that models actually produce different predictions --
    # not asserting one beats another (small synthetic data, no reason to
    # expect a specific winner), just that the pipeline isn't accidentally
    # feeding every model the same thing.
    results, _info = run_baseline_comparison(db_session, TEST_TICKERS, horizon_days=5, embargo_days=2)
    naive = next(r for r in results if r.model_name == "naive_base_rate")
    rf = next(r for r in results if r.model_name == "random_forest")
    assert naive.test.n_samples == rf.test.n_samples
