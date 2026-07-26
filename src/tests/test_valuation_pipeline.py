"""Integration tests for the valuation pipeline -- requires a live
database. Uses a fixture company (never a real ticker's row) -- see
``test_ingestion_fundamentals.py``'s module docstring for why real
tickers are unsafe for tests that write/delete rows scoped by company_id.
"""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models.company import Company
from src.database.models.fundamentals import FinancialRatio, FinancialStatementItem, FinancialStatementRaw
from src.database.models.market import MarketPriceClean
from src.database.models.mixins import QualityStatus
from src.database.models.ml import ValuationResult
from src.database.models.ops import DataSourceRegistry
from src.database.session import make_engine
from src.valuation.pipeline import compute_valuation

pytestmark = pytest.mark.integration


@pytest.fixture()
def db_session():
    engine = make_engine("postgresql+psycopg://idx:idx@localhost:5433/idx_intelligence")
    with Session(engine) as session:
        yield session
        session.rollback()


def _make_source(session: Session, name: str) -> DataSourceRegistry:
    source = session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == name))
    if source is None:
        source = DataSourceRegistry(name=name, category="fundamentals", access_type="internal_derived", is_active=True)
        session.add(source)
        session.flush()
    return source


@pytest.fixture()
def company_with_valuation_inputs(db_session):
    company = db_session.scalar(select(Company).where(Company.ticker == "ZZZV"))
    if company is None:
        company = Company(ticker="ZZZV", company_name="Test Fixture Valuation Co")
        db_session.add(company)
        db_session.flush()
    source = _make_source(db_session, "fake_valuation_source")
    now = dt.datetime.now(dt.UTC)

    # 5 historical P/E and P/B ratio points, and a latest EPS statement item.
    for i, (pe, pb) in enumerate([(8.0, 1.0), (9.0, 1.2), (10.0, 1.4), (11.0, 1.6), (12.0, 1.8)]):
        available_at = dt.datetime(2022 + i, 4, 30, tzinfo=dt.UTC)
        db_session.add_all(
            [
                FinancialRatio(
                    company_id=company.id, ratio_name="price_to_earnings__annual", value=pe, is_applicable=True,
                    computation_version="v1", source_id=source.id, retrieved_at=now, available_at=available_at,
                    period_end=dt.date(2021 + i, 12, 31), currency="IDR", unit="unit", is_restated=False,
                    quality_status=QualityStatus.VALID,
                ),
                FinancialRatio(
                    company_id=company.id, ratio_name="price_to_book__annual", value=pb, is_applicable=True,
                    computation_version="v1", source_id=source.id, retrieved_at=now, available_at=available_at,
                    period_end=dt.date(2021 + i, 12, 31), currency="IDR", unit="unit", is_restated=False,
                    quality_status=QualityStatus.VALID,
                ),
                FinancialRatio(
                    company_id=company.id, ratio_name="book_value_per_share__annual", value=50.0 + i, is_applicable=True,
                    computation_version="v1", source_id=source.id, retrieved_at=now, available_at=available_at,
                    period_end=dt.date(2021 + i, 12, 31), currency="IDR", unit="unit", is_restated=False,
                    quality_status=QualityStatus.VALID,
                ),
            ]
        )
    statement = FinancialStatementRaw(
        company_id=company.id, statement_type="annual", fiscal_period="2025FY", source_format="json_csv_xlsx",
        statement_currency="IDR", scale="unit", source_id=source.id, retrieved_at=now,
        available_at=dt.datetime(2026, 4, 30, tzinfo=dt.UTC), period_end=dt.date(2025, 12, 31),
        currency="IDR", unit="unit", is_restated=False, quality_status=QualityStatus.VALID,
    )
    db_session.add(statement)
    db_session.flush()
    db_session.add(
        FinancialStatementItem(
            statement_id=statement.id,
            company_id=company.id, statement_section="income_statement", account_code="eps_diluted",
            account_name_reported="eps_diluted", value=10.0, source_id=source.id, retrieved_at=now,
            available_at=dt.datetime(2026, 4, 30, tzinfo=dt.UTC), period_end=dt.date(2025, 12, 31),
            currency="IDR", unit="unit", is_restated=False, quality_status=QualityStatus.VALID,
        )
    )
    db_session.add(
        MarketPriceClean(
            company_id=company.id, trade_date=dt.date(2026, 7, 20), close=95.0,
            source_id=source.id, retrieved_at=now, available_at=now, currency="IDR", unit="unit",
            quality_status=QualityStatus.VALID,
        )
    )
    db_session.commit()
    yield company
    db_session.query(ValuationResult).filter(ValuationResult.company_id == company.id).delete()
    db_session.query(FinancialRatio).filter(FinancialRatio.company_id == company.id).delete()
    db_session.query(FinancialStatementItem).filter(FinancialStatementItem.company_id == company.id).delete()
    db_session.query(FinancialStatementRaw).filter(FinancialStatementRaw.company_id == company.id).delete()
    db_session.query(MarketPriceClean).filter(MarketPriceClean.company_id == company.id).delete()
    db_session.query(Company).filter(Company.id == company.id).delete()
    db_session.query(DataSourceRegistry).filter(DataSourceRegistry.name == "fake_valuation_source").delete()
    db_session.commit()


def test_compute_valuation_writes_expected_fair_values(db_session, company_with_valuation_inputs):
    company = company_with_valuation_inputs
    outcome = compute_valuation(db_session, "ZZZV", as_of_date=dt.date(2026, 7, 24))
    db_session.commit()

    assert outcome.skipped_reason is None
    assert set(outcome.methods_used) == {"relative_pe_historical", "relative_pb_historical"}

    result = db_session.scalar(
        select(ValuationResult).where(ValuationResult.company_id == company.id, ValuationResult.as_of_date == dt.date(2026, 7, 24))
    )
    assert result is not None
    # P/E method: EPS=10.0, historical P/E median=10.0 -> base=100.0
    # P/B method: BVPS=54.0 (latest, i=4), historical P/B median=1.4 -> base=75.6
    # combined base = average of the two
    assert float(result.fair_value_base) == pytest.approx((100.0 + 75.6) / 2, rel=1e-3)
    assert float(result.fair_value_bear) < float(result.fair_value_base) < float(result.fair_value_bull)
    assert result.sensitivity["current_price"] == 95.0


def test_compute_valuation_is_idempotent_per_day_not_across_days(db_session, company_with_valuation_inputs):
    company = company_with_valuation_inputs
    compute_valuation(db_session, "ZZZV", as_of_date=dt.date(2026, 7, 23))
    db_session.commit()
    compute_valuation(db_session, "ZZZV", as_of_date=dt.date(2026, 7, 23))  # rerun same day
    db_session.commit()
    compute_valuation(db_session, "ZZZV", as_of_date=dt.date(2026, 7, 24))  # a different day
    db_session.commit()

    rows = db_session.scalars(select(ValuationResult).where(ValuationResult.company_id == company.id)).all()
    dates = sorted(r.as_of_date for r in rows)
    assert dates == [dt.date(2026, 7, 23), dt.date(2026, 7, 24)]  # same-day rerun replaced, not duplicated; both days kept


def test_compute_valuation_skips_unknown_ticker(db_session):
    outcome = compute_valuation(db_session, "NOPE_NOT_REAL")
    assert outcome.skipped_reason is not None


def test_compute_valuation_skips_insufficient_history(db_session):
    company = Company(ticker="ZZZW", company_name="No Fundamentals Yet")
    db_session.add(company)
    db_session.commit()
    try:
        outcome = compute_valuation(db_session, "ZZZW")
        assert outcome.skipped_reason is not None
        assert "insufficient" in outcome.skipped_reason
    finally:
        db_session.query(Company).filter(Company.id == company.id).delete()
        db_session.commit()
