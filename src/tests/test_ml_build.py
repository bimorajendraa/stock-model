"""Integration tests for dataset assembly -- requires a live database."""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models.company import Company
from src.database.models.features import TechnicalFeature
from src.database.models.fundamentals import FinancialRatio
from src.database.models.market import MarketPriceClean
from src.database.models.mixins import QualityStatus
from src.database.models.ops import DataSourceRegistry
from src.database.session import make_engine
from src.features.technical.pipeline import compute_technical_features
from src.ml.datasets.build import build_labeled_dataset, split_dataset

pytestmark = pytest.mark.integration


@pytest.fixture()
def db_session():
    engine = make_engine("postgresql+psycopg://idx:idx@localhost:5433/idx_intelligence")
    with Session(engine) as session:
        yield session
        session.rollback()


@pytest.fixture()
def company_with_features(db_session):
    company = db_session.scalar(select(Company).where(Company.ticker == "ZZZL"))
    if company is None:
        company = Company(ticker="ZZZL", company_name="Test Fixture Company ML")
        db_session.add(company)
        db_session.flush()

    source = db_session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == "fake_ml_source"))
    if source is None:
        source = DataSourceRegistry(name="fake_ml_source", category="market", access_type="internal_derived", is_active=True)
        db_session.add(source)
        db_session.flush()

    now = dt.datetime.now(dt.UTC)
    start = dt.date(2025, 1, 1)
    price = 1000.0
    for i in range(120):
        d = start + dt.timedelta(days=i)
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
    compute_technical_features(db_session, "ZZZL")
    db_session.commit()

    yield company

    db_session.query(TechnicalFeature).filter(TechnicalFeature.company_id == company.id).delete()
    db_session.query(MarketPriceClean).filter(MarketPriceClean.company_id == company.id).delete()
    db_session.query(DataSourceRegistry).filter(DataSourceRegistry.name == "fake_ml_source").delete()
    db_session.query(Company).filter(Company.id == company.id).delete()
    db_session.commit()


def test_build_labeled_dataset_has_features_and_labels(db_session, company_with_features):
    df = build_labeled_dataset(db_session, ["ZZZL"], horizons=(5, 20))
    assert not df.empty
    assert "sma_5" in df.columns
    assert "fwd_return_5d" in df.columns
    assert "direction_20d" in df.columns
    assert (df["ticker"] == "ZZZL").all()


def test_build_labeled_dataset_drops_rows_with_no_label(db_session, company_with_features):
    df = build_labeled_dataset(db_session, ["ZZZL"], horizons=(5,))
    # last 5 rows of history can't have a 5-day forward return -- must not
    # be present with an all-NaN label row
    assert df["fwd_return_5d"].notna().any()
    max_date_with_data = df["feature_date"].max()
    assert max_date_with_data <= dt.date(2025, 1, 1) + dt.timedelta(days=120 - 5)


def test_split_dataset_produces_three_non_overlapping_parts(db_session, company_with_features):
    df = build_labeled_dataset(db_session, ["ZZZL"], horizons=(5,))
    parts, split = split_dataset(df, horizon_days=5, embargo_days=2)
    assert split.train_end < split.validation_start
    total = len(parts["train"]) + len(parts["validation"]) + len(parts["test"])
    assert total <= len(df)  # purging can only remove rows, never add
    assert total > 0


@pytest.fixture()
def company_with_fundamentals(db_session, company_with_features):
    company = company_with_features
    source = db_session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == "fake_ml_source"))
    now = dt.datetime.now(dt.UTC)
    # price history fixture runs 2025-01-01 for 120 days
    ratio_rows = [
        FinancialRatio(
            company_id=company.id, ratio_name="net_margin__annual", value=0.10, is_applicable=True,
            computation_version="v1", source_id=source.id, retrieved_at=now,
            available_at=dt.datetime(2025, 1, 20, tzinfo=dt.UTC), period_end=dt.date(2024, 12, 31),
            currency="IDR", unit="unit", is_restated=False, quality_status=QualityStatus.VALID,
        ),
        FinancialRatio(
            # A later (quarterly) statement supersedes the earlier annual
            # one's value once it becomes available -- point-in-time
            # "most recently known", not "always prefer annual".
            company_id=company.id, ratio_name="net_margin__quarterly", value=0.20, is_applicable=True,
            computation_version="v1", source_id=source.id, retrieved_at=now,
            available_at=dt.datetime(2025, 3, 1, tzinfo=dt.UTC), period_end=dt.date(2025, 1, 31),
            currency="IDR", unit="unit", is_restated=False, quality_status=QualityStatus.VALID,
        ),
        FinancialRatio(
            company_id=company.id, ratio_name="roe__annual", value=None, is_applicable=False,
            computation_version="v1", source_id=source.id, retrieved_at=now,
            available_at=dt.datetime(2025, 1, 20, tzinfo=dt.UTC), period_end=dt.date(2024, 12, 31),
            currency="IDR", unit="unit", is_restated=False, quality_status=QualityStatus.VALID,
        ),
    ]
    db_session.add_all(ratio_rows)
    db_session.commit()
    yield company
    db_session.query(FinancialRatio).filter(FinancialRatio.company_id == company.id).delete()
    db_session.commit()


def test_build_labeled_dataset_default_has_no_fundamental_columns(db_session, company_with_fundamentals):
    # include_fundamentals defaults to False -- must not change behavior
    # for any existing caller that doesn't opt in.
    df = build_labeled_dataset(db_session, ["ZZZL"], horizons=(5,))
    assert not any(c.startswith("fund_") for c in df.columns)


def test_build_labeled_dataset_include_fundamentals_is_point_in_time(db_session, company_with_fundamentals):
    df = build_labeled_dataset(db_session, ["ZZZL"], horizons=(5,), include_fundamentals=True)
    assert "fund_net_margin" in df.columns

    before = df[df["feature_date"] < dt.date(2025, 1, 20)]
    mid = df[(df["feature_date"] >= dt.date(2025, 1, 20)) & (df["feature_date"] < dt.date(2025, 3, 1))]
    after = df[df["feature_date"] >= dt.date(2025, 3, 1)]

    assert not before.empty and not mid.empty and not after.empty
    assert before["fund_net_margin"].isna().all()  # no statement public yet -- must not leak a future value back
    assert (mid["fund_net_margin"] == 0.10).all()  # annual statement's value, once available
    assert (after["fund_net_margin"] == 0.20).all()  # superseded once the later quarterly statement is available

    # roe's only fixture row is is_applicable=False, and this fixture has
    # no other company in the query, so fund_roe has zero applicable
    # values anywhere in this dataset -- it must not appear as a phantom
    # always-NaN column (never a fabricated 0 either way).
    assert "fund_roe" not in df.columns
