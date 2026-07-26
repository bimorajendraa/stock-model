"""Integration tests for the fundamental ratio pipeline -- requires a
live database. Uses fixture statements (not real Yahoo data) so the
expected ratio values are exact and don't depend on live data changing.
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
from src.database.models.ops import DataSourceRegistry
from src.database.session import make_engine
from src.features.fundamentals.pipeline import compute_fundamental_ratios

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
        source = DataSourceRegistry(name=name, category="fundamentals", access_type="fallback_provider", is_active=True)
        session.add(source)
        session.flush()
    return source


def _add_statement(
    session: Session,
    company: Company,
    source: DataSourceRegistry,
    *,
    statement_type: str,
    fiscal_period: str,
    period_end: dt.date,
    available_at: dt.datetime,
    items: dict[str, float],
    quality_status: QualityStatus = QualityStatus.VALID,
) -> FinancialStatementRaw:
    now = dt.datetime.now(dt.UTC)
    raw = FinancialStatementRaw(
        company_id=company.id,
        statement_type=statement_type,
        fiscal_period=fiscal_period,
        source_format="json_csv_xlsx",
        statement_currency="IDR",
        scale="unit",
        source_id=source.id,
        retrieved_at=now,
        available_at=available_at,
        period_end=period_end,
        currency="IDR",
        unit="unit",
        is_restated=False,
        quality_status=quality_status,
    )
    session.add(raw)
    session.flush()
    for account_code, value in items.items():
        session.add(
            FinancialStatementItem(
                statement_id=raw.id,
                company_id=company.id,
                statement_section="income_statement",  # not exercised by the pipeline, arbitrary for the fixture
                account_code=account_code,
                account_name_reported=account_code,
                value=value,
                source_id=source.id,
                retrieved_at=now,
                available_at=available_at,
                period_end=period_end,
                currency="IDR",
                unit="unit",
                is_restated=False,
                quality_status=quality_status,
            )
        )
    return raw


@pytest.fixture()
def company_with_statements(db_session):
    company = db_session.scalar(select(Company).where(Company.ticker == "ZZZR"))
    if company is None:
        company = Company(ticker="ZZZR", company_name="Test Fixture Ratios Co")
        db_session.add(company)
        db_session.flush()
    source = _make_source(db_session, "fake_ratio_fixture_source")
    db_session.commit()
    yield company, source
    db_session.query(FinancialRatio).filter(FinancialRatio.company_id == company.id).delete()
    db_session.query(FinancialStatementItem).filter(FinancialStatementItem.company_id == company.id).delete()
    db_session.query(FinancialStatementRaw).filter(FinancialStatementRaw.company_id == company.id).delete()
    db_session.query(MarketPriceClean).filter(MarketPriceClean.company_id == company.id).delete()
    db_session.query(Company).filter(Company.id == company.id).delete()
    db_session.query(DataSourceRegistry).filter(DataSourceRegistry.name == "fake_ratio_fixture_source").delete()
    db_session.commit()


def test_compute_fundamental_ratios_from_full_statement(db_session, company_with_statements):
    company, source = company_with_statements
    available_at = dt.datetime(2026, 4, 30, tzinfo=dt.UTC)
    _add_statement(
        db_session,
        company,
        source,
        statement_type="annual",
        fiscal_period="2025FY",
        period_end=dt.date(2025, 12, 31),
        available_at=available_at,
        items={
            "revenue": 1000.0,
            "net_income": 100.0,
            "total_equity": 500.0,
            "total_assets": 2000.0,
            "total_debt": 300.0,
            "shares_outstanding": 1000.0,
            "eps_diluted": 0.1,
        },
    )
    db_session.commit()

    outcome = compute_fundamental_ratios(db_session, "ZZZR")
    db_session.commit()

    assert outcome.skipped_reason is None
    assert outcome.statements_processed == 1
    assert outcome.ratios_written == 13  # every RATIO_NAMES entry, applicable or not

    net_margin = db_session.scalar(
        select(FinancialRatio).where(
            FinancialRatio.company_id == company.id, FinancialRatio.ratio_name == "net_margin__annual"
        )
    )
    assert net_margin is not None
    assert float(net_margin.value) == pytest.approx(0.1)
    assert net_margin.is_applicable is True

    # gross_margin needs gross_profit, which this fixture doesn't report
    # (bank-like statement) -- must be written as not_applicable, not
    # dropped or fabricated as 0.
    gross_margin = db_session.scalar(
        select(FinancialRatio).where(
            FinancialRatio.company_id == company.id, FinancialRatio.ratio_name == "gross_margin__annual"
        )
    )
    assert gross_margin is not None
    assert gross_margin.value is None
    assert gross_margin.is_applicable is False


def test_price_dependent_ratios_use_point_in_time_price(db_session, company_with_statements):
    company, source = company_with_statements
    available_at = dt.datetime(2026, 4, 30, tzinfo=dt.UTC)
    _add_statement(
        db_session,
        company,
        source,
        statement_type="annual",
        fiscal_period="2025FY",
        period_end=dt.date(2025, 12, 31),
        available_at=available_at,
        items={"total_equity": 500.0, "shares_outstanding": 1000.0, "eps_diluted": 0.1},
    )
    now = dt.datetime.now(dt.UTC)
    db_session.add_all(
        [
            MarketPriceClean(
                company_id=company.id, trade_date=dt.date(2026, 4, 29), close=10.0,  # on/before available_at -- must be used
                source_id=source.id, retrieved_at=now, available_at=now, currency="IDR", unit="unit",
                quality_status=QualityStatus.VALID,
            ),
            MarketPriceClean(
                company_id=company.id, trade_date=dt.date(2026, 5, 1), close=999.0,  # AFTER available_at -- must NOT leak in
                source_id=source.id, retrieved_at=now, available_at=now, currency="IDR", unit="unit",
                quality_status=QualityStatus.VALID,
            ),
        ]
    )
    db_session.commit()

    compute_fundamental_ratios(db_session, "ZZZR")
    db_session.commit()

    pbv = db_session.scalar(
        select(FinancialRatio).where(
            FinancialRatio.company_id == company.id, FinancialRatio.ratio_name == "price_to_book__annual"
        )
    )
    assert float(pbv.value) == pytest.approx(10.0 / 0.5)  # uses the 10.0 price, never the future 999.0


def test_insufficient_statements_are_excluded(db_session, company_with_statements):
    company, source = company_with_statements
    _add_statement(
        db_session,
        company,
        source,
        statement_type="quarterly",
        fiscal_period="2025Q3",
        period_end=dt.date(2025, 9, 30),
        available_at=dt.datetime(2025, 11, 29, tzinfo=dt.UTC),
        items={"net_income": 5.0},  # thin, matches real observed sparsity
        quality_status=QualityStatus.INSUFFICIENT,
    )
    db_session.commit()

    outcome = compute_fundamental_ratios(db_session, "ZZZR")

    assert outcome.skipped_reason is not None
    assert outcome.statements_processed == 0
    assert outcome.ratios_written == 0


def test_annual_and_quarterly_same_period_end_do_not_collide(db_session, company_with_statements):
    company, source = company_with_statements
    shared_period_end = dt.date(2025, 12, 31)
    _add_statement(
        db_session, company, source, statement_type="annual", fiscal_period="2025FY",
        period_end=shared_period_end, available_at=dt.datetime(2026, 4, 30, tzinfo=dt.UTC),
        items={"revenue": 1000.0, "net_income": 100.0},
    )
    _add_statement(
        db_session, company, source, statement_type="quarterly", fiscal_period="2025Q4",
        period_end=shared_period_end, available_at=dt.datetime(2026, 3, 1, tzinfo=dt.UTC),
        items={"revenue": 300.0, "net_income": 20.0},
    )
    db_session.commit()

    outcome = compute_fundamental_ratios(db_session, "ZZZR")
    db_session.commit()

    assert outcome.statements_processed == 2
    annual_margin = db_session.scalar(
        select(FinancialRatio).where(
            FinancialRatio.company_id == company.id, FinancialRatio.ratio_name == "net_margin__annual"
        )
    )
    quarterly_margin = db_session.scalar(
        select(FinancialRatio).where(
            FinancialRatio.company_id == company.id, FinancialRatio.ratio_name == "net_margin__quarterly"
        )
    )
    assert float(annual_margin.value) == pytest.approx(0.1)
    assert float(quarterly_margin.value) == pytest.approx(20.0 / 300.0)


def test_compute_fundamental_ratios_is_idempotent(db_session, company_with_statements):
    company, source = company_with_statements
    _add_statement(
        db_session, company, source, statement_type="annual", fiscal_period="2025FY",
        period_end=dt.date(2025, 12, 31), available_at=dt.datetime(2026, 4, 30, tzinfo=dt.UTC),
        items={"revenue": 1000.0, "net_income": 100.0},
    )
    db_session.commit()

    first = compute_fundamental_ratios(db_session, "ZZZR")
    db_session.commit()
    second = compute_fundamental_ratios(db_session, "ZZZR")
    db_session.commit()

    assert first.ratios_written == second.ratios_written
    rows = db_session.scalars(select(FinancialRatio).where(FinancialRatio.company_id == company.id)).all()
    assert len(rows) == first.ratios_written  # no duplicate accumulation


def test_compute_fundamental_ratios_skips_unknown_ticker(db_session):
    outcome = compute_fundamental_ratios(db_session, "NOPE_NOT_REAL")
    assert outcome.skipped_reason is not None


def test_compute_fundamental_ratios_skips_ticker_with_no_statements(db_session):
    company = Company(ticker="ZZZS", company_name="No Statements Yet")
    db_session.add(company)
    db_session.commit()
    try:
        outcome = compute_fundamental_ratios(db_session, "ZZZS")
        assert outcome.skipped_reason is not None
        assert "fundamentals sync" in outcome.skipped_reason
    finally:
        db_session.query(Company).filter(Company.id == company.id).delete()
        db_session.commit()
