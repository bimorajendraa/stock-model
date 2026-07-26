"""Integration tests for sector classification -- requires a live
database, hits the real Yahoo Finance API (no mock), consistent with how
every other external call in this project is verified.

Uses the real BBCA company row (restoring its original
``sector_registry_id`` afterward, same pattern as
``test_market_cap.py``'s shares_outstanding restore) -- unlike the
fundamentals-ingestion incident this project learned from, setting one
scalar FK and restoring it afterward is safe; it never clears/deletes
other rows scoped by company_id. Any ``SectorRegistry`` row created here
is real, legitimate, reusable classification data other companies would
also reference -- not a fixture needing cleanup.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models.company import Company, SectorRegistry
from src.database.session import make_engine
from src.ingestion.sector_classification import _sector_code, fetch_and_store_sector

pytestmark = pytest.mark.integration


@pytest.fixture()
def db_session():
    engine = make_engine("postgresql+psycopg://idx:idx@localhost:5433/idx_intelligence")
    with Session(engine) as session:
        yield session
        session.rollback()


def test_fetch_and_store_sector_real_ticker(db_session):
    company = db_session.scalar(select(Company).where(Company.ticker == "BBCA"))
    if company is None:
        pytest.skip("BBCA not present in this database")
    original_sector_id = company.sector_registry_id

    outcome = fetch_and_store_sector(db_session, "BBCA")
    db_session.commit()

    assert outcome.skipped_reason is None
    # BBCA is a bank -- real GICS-style classification, not fabricated.
    assert outcome.sector == "Financial Services"
    assert "Bank" in (outcome.industry or "")

    db_session.refresh(company)
    assert company.sector_registry_id is not None
    sector = db_session.get(SectorRegistry, company.sector_registry_id)
    assert sector.sector_name == "Financial Services"

    company.sector_registry_id = original_sector_id  # restore
    db_session.commit()


def test_fetch_and_store_sector_is_idempotent_no_duplicate_sector_rows(db_session):
    company = db_session.scalar(select(Company).where(Company.ticker == "BBCA"))
    if company is None:
        pytest.skip("BBCA not present in this database")
    original_sector_id = company.sector_registry_id

    first_outcome = fetch_and_store_sector(db_session, "BBCA")
    db_session.commit()
    first_sector_id = company.sector_registry_id

    fetch_and_store_sector(db_session, "BBCA")
    db_session.commit()

    assert company.sector_registry_id == first_sector_id  # same row reused, not a new duplicate
    expected_code = _sector_code(first_outcome.sector, first_outcome.industry)
    matching = db_session.scalars(select(SectorRegistry).where(SectorRegistry.sector_code == expected_code)).all()
    # exactly one row for this (sector, industry) pair, regardless of how many times fetched
    assert len(matching) == 1
    assert matching[0].id == first_sector_id

    company.sector_registry_id = original_sector_id  # restore
    db_session.commit()


def test_two_industries_in_the_same_broad_sector_get_distinct_rows(db_session):
    # Real bug this project hit live: sector_code has a global UNIQUE
    # constraint, so two different industries under the same broad sector
    # (e.g. "Financial Services" -> "Banks - Regional" vs. "Insurance -
    # Property & Casualty") must NOT collide. Tests the private helper
    # directly with synthetic names -- deterministic, doesn't depend on
    # which real companies happen to be in this database.
    from src.ingestion.sector_classification import _get_or_create_sector

    marker = "zzztest"  # keeps these rows identifiable for cleanup, distinct from any real sector name
    try:
        row_a = _get_or_create_sector(db_session, f"{marker} Financial Services", f"{marker} Banks - Regional")
        row_b = _get_or_create_sector(
            db_session, f"{marker} Financial Services", f"{marker} Insurance - Property & Casualty"
        )
        db_session.commit()

        assert row_a.id != row_b.id  # distinct rows, no UniqueViolation
        assert row_a.sector_name == row_b.sector_name == f"{marker} Financial Services"
        assert row_a.sector_code != row_b.sector_code
    finally:
        db_session.query(SectorRegistry).filter(SectorRegistry.sector_name == f"{marker} Financial Services").delete()
        db_session.commit()


def test_fetch_and_store_sector_unknown_ticker(db_session):
    outcome = fetch_and_store_sector(db_session, "NOPE_NOT_REAL")
    assert outcome.skipped_reason is not None
