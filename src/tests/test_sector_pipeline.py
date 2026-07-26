"""Integration tests for the sector-relative metrics pipeline -- requires
a live database. Uses a fixture sector (marked "zzztest") and fixture
companies -- never a real sector, so cleanup can't collide with real
production classification.
"""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models.company import Company, SectorRegistry
from src.database.models.fundamentals import FinancialRatio
from src.database.models.mixins import QualityStatus
from src.database.models.ops import DataSourceRegistry
from src.database.models.sector import SectorSpecificMetric
from src.database.session import make_engine
from src.features.sector.pipeline import compute_sector_relative_metrics

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
def sector_with_companies(db_session):
    sector = SectorRegistry(
        sector_code="zzztest_sector",
        sector_name="ZZZ Test Sector",
        subsector_code="zzztest_sub",
        subsector_name="ZZZ Test Subsector",
        metrics_config_key="zzztest_sector",
        valuation_config_key="zzztest_sector",
    )
    db_session.add(sector)
    db_session.flush()

    source = _make_source(db_session, "fake_sector_test_source")
    now = dt.datetime.now(dt.UTC)
    companies = []
    # 4 companies with real, distinct net_margin values -- roe/debt_to_equity
    # deliberately left unset on one company to test partial-peer-group handling.
    for i, (ticker, net_margin) in enumerate([("ZZZS1", 0.05), ("ZZZS2", 0.10), ("ZZZS3", 0.15), ("ZZZS4", 0.20)]):
        company = Company(ticker=ticker, company_name=f"Test {ticker}", sector_registry_id=sector.id)
        db_session.add(company)
        db_session.flush()
        companies.append(company)
        db_session.add(
            FinancialRatio(
                company_id=company.id, ratio_name="net_margin__annual", value=net_margin, is_applicable=True,
                computation_version="v1", source_id=source.id, retrieved_at=now,
                available_at=dt.datetime(2026, 4, 30, tzinfo=dt.UTC), period_end=dt.date(2025, 12, 31),
                currency="IDR", unit="unit", is_restated=False, quality_status=QualityStatus.VALID,
            )
        )
        if i < 3:  # ZZZS4 deliberately has no roe -- must not block the other 3's roe ranking
            db_session.add(
                FinancialRatio(
                    company_id=company.id, ratio_name="roe__annual", value=0.05 * (i + 1), is_applicable=True,
                    computation_version="v1", source_id=source.id, retrieved_at=now,
                    available_at=dt.datetime(2026, 4, 30, tzinfo=dt.UTC), period_end=dt.date(2025, 12, 31),
                    currency="IDR", unit="unit", is_restated=False, quality_status=QualityStatus.VALID,
                )
            )
    db_session.commit()
    yield sector, companies
    for company in companies:
        db_session.query(SectorSpecificMetric).filter(SectorSpecificMetric.company_id == company.id).delete()
        db_session.query(FinancialRatio).filter(FinancialRatio.company_id == company.id).delete()
        db_session.query(Company).filter(Company.id == company.id).delete()
    db_session.query(SectorRegistry).filter(SectorRegistry.id == sector.id).delete()
    db_session.query(DataSourceRegistry).filter(DataSourceRegistry.name == "fake_sector_test_source").delete()
    db_session.commit()


def test_compute_sector_relative_metrics_ranks_real_peers(db_session, sector_with_companies):
    sector, companies = sector_with_companies
    outcome = compute_sector_relative_metrics(db_session, sector.id)
    db_session.commit()

    assert outcome.skipped_reason is None
    assert outcome.companies_considered == 4

    zzz_s1, zzz_s4 = companies[0], companies[3]
    lowest = db_session.scalar(
        select(SectorSpecificMetric).where(
            SectorSpecificMetric.company_id == zzz_s1.id, SectorSpecificMetric.metric_name == "net_margin_percentile_in_sector"
        )
    )
    highest = db_session.scalar(
        select(SectorSpecificMetric).where(
            SectorSpecificMetric.company_id == zzz_s4.id, SectorSpecificMetric.metric_name == "net_margin_percentile_in_sector"
        )
    )
    assert float(lowest.value) < float(highest.value)  # 0.05 net_margin ranks below 0.20's


def test_compute_sector_relative_metrics_missing_ratio_does_not_block_others(db_session, sector_with_companies):
    sector, companies = sector_with_companies
    compute_sector_relative_metrics(db_session, sector.id)
    db_session.commit()

    zzz_s4 = companies[3]  # deliberately has no roe
    roe_metric = db_session.scalar(
        select(SectorSpecificMetric).where(
            SectorSpecificMetric.company_id == zzz_s4.id, SectorSpecificMetric.metric_name == "roe_percentile_in_sector"
        )
    )
    assert roe_metric is None  # correctly absent, never a fabricated rank for a missing value

    net_margin_metric = db_session.scalar(
        select(SectorSpecificMetric).where(
            SectorSpecificMetric.company_id == zzz_s4.id, SectorSpecificMetric.metric_name == "net_margin_percentile_in_sector"
        )
    )
    assert net_margin_metric is not None  # net_margin still ranked despite missing roe


def test_compute_sector_relative_metrics_is_idempotent(db_session, sector_with_companies):
    sector, companies = sector_with_companies
    first = compute_sector_relative_metrics(db_session, sector.id)
    db_session.commit()
    second = compute_sector_relative_metrics(db_session, sector.id)
    db_session.commit()

    assert first.metrics_written == second.metrics_written
    rows = db_session.scalars(
        select(SectorSpecificMetric).where(SectorSpecificMetric.company_id.in_([c.id for c in companies]))
    ).all()
    assert len(rows) == first.metrics_written  # no duplicate accumulation


def test_compute_sector_relative_metrics_unknown_sector(db_session):
    outcome = compute_sector_relative_metrics(db_session, 999_999_999)
    assert outcome.skipped_reason is not None
