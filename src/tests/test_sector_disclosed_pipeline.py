"""Integration test for disclosed bank metrics persistence."""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models.company import Company, SectorRegistry
from src.database.models.fundamentals import FinancialStatementItem, FinancialStatementRaw
from src.database.models.mixins import QualityStatus
from src.database.models.ops import DataSourceRegistry
from src.database.models.sector import SectorSpecificMetric
from src.database.session import make_engine
from src.features.sector.disclosed_pipeline import compute_disclosed_sector_metrics

pytestmark = pytest.mark.integration

_TICKER = "ZZZBANKMET"
_SECTOR_CODE = "zzz_bank_metrics"
_SOURCE = "zzz_idx_xbrl_metrics_source"


@pytest.fixture()
def db_session():
    engine = make_engine("postgresql+psycopg://idx:idx@localhost:5433/idx_intelligence")
    with Session(engine) as session:
        yield session
        session.rollback()


def _cleanup(session: Session) -> None:
    company = session.scalar(select(Company).where(Company.ticker == _TICKER))
    if company:
        session.query(SectorSpecificMetric).filter(SectorSpecificMetric.company_id == company.id).delete()
        session.query(FinancialStatementItem).filter(FinancialStatementItem.company_id == company.id).delete()
        session.query(FinancialStatementRaw).filter(FinancialStatementRaw.company_id == company.id).delete()
        session.delete(company)
    sector = session.scalar(select(SectorRegistry).where(SectorRegistry.sector_code == _SECTOR_CODE))
    if sector:
        session.delete(sector)
    source = session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == _SOURCE))
    if source:
        session.delete(source)
    session.commit()


def test_disclosed_bank_metrics_are_written_with_filing_lineage(db_session):
    _cleanup(db_session)
    sector = SectorRegistry(
        sector_code=_SECTOR_CODE,
        sector_name="Financial Services",
        subsector_name="Banks - Regional",
        metrics_config_key="banks",
        valuation_config_key="banks",
    )
    source = DataSourceRegistry(
        name=_SOURCE,
        category="fundamentals",
        access_type="official",
        is_active=True,
    )
    db_session.add_all([sector, source])
    db_session.flush()
    company = Company(ticker=_TICKER, company_name="Fixture Bank", sector_registry_id=sector.id)
    db_session.add(company)
    db_session.flush()
    published_at = dt.datetime(2026, 1, 31, tzinfo=dt.UTC)
    statement = FinancialStatementRaw(
        company_id=company.id,
        statement_type="annual",
        fiscal_period="2025FY",
        source_format="xbrl",
        statement_currency="IDR",
        scale="unit",
        source_id=source.id,
        retrieved_at=published_at,
        available_at=published_at,
        period_end=dt.date(2025, 12, 31),
        currency="IDR",
        unit="unit",
        is_restated=False,
        quality_status=QualityStatus.VALID,
    )
    db_session.add(statement)
    db_session.flush()
    facts = {
        "gross_loans": 1_000.0,
        "non_performing_loans_gross": 20.0,
        "customer_deposits": 1_250.0,
        "current_accounts": 300.0,
        "savings_accounts": 200.0,
        "net_interest_margin_reported": 0.05,
        "regulatory_capital": 250.0,
        "risk_weighted_assets": 1_000.0,
    }
    for code, value in facts.items():
        db_session.add(
            FinancialStatementItem(
                statement_id=statement.id,
                company_id=company.id,
                statement_section="notes",
                account_code=code,
                account_name_reported=code,
                value=value,
                source_id=source.id,
                retrieved_at=published_at,
                available_at=published_at,
                period_end=statement.period_end,
                currency="IDR",
                unit="unit",
                is_restated=False,
                quality_status=QualityStatus.VALID,
            )
        )
    db_session.commit()

    try:
        outcome = compute_disclosed_sector_metrics(db_session, _TICKER)
        db_session.commit()
        assert outcome.skipped_reason is None
        rows = list(
            db_session.scalars(
                select(SectorSpecificMetric).where(SectorSpecificMetric.company_id == company.id)
            )
        )
        values = {row.metric_name: float(row.value) for row in rows}
        assert values["npl_gross_pct"] == pytest.approx(2.0)
        assert values["net_interest_margin_pct"] == pytest.approx(5.0)
        assert values["capital_adequacy_ratio_pct"] == pytest.approx(25.0)
        assert all(row.source_id == source.id for row in rows)
        assert all(row.available_at == published_at for row in rows)
    finally:
        _cleanup(db_session)
