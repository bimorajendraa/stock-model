"""Integration tests for fundamentals ingestion -- requires a live
database. Most tests hit the real Yahoo Finance API (no mock), consistent
with how every other ingestion path in this project is verified; the
completeness/quality_status tests use a small fake provider instead so
they're deterministic (real-data sparsity isn't guaranteed to reproduce
the same sparse period forever).

**Every test here uses a dedicated fixture Company, never a real ticker's
row directly** -- ``ingest_fundamentals`` does a full clear-then-rewrite
of ALL statements for a company_id, and test cleanup deletes everything
for that company_id too. An earlier version of this file used the real
"BBCA" ticker directly and its cleanup wiped BBCA's real production
statements the first time this suite ran after a real ingestion (caught
during a follow-up audit, not by the tests themselves -- a reminder that
"tests pass" isn't the same as "tests are safe to run against a live
database"). Real Yahoo data is still fetched for real BBCA -- the fixture
company just uses a fake ticker string with the adapter's
``symbol_resolver`` overridden to the real ``BBCA.JK`` symbol, so the
provider call is real but the row it's stored under is disposable.
"""
from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.data_sources.base import AccessType, SourceDescriptor, SourcedValue, ValidationStatus
from src.data_sources.fundamentals.base import FinancialStatementDocument, FundamentalsProvider
from src.data_sources.fundamentals.taxonomy import ACCOUNT_CODE_SECTIONS
from src.data_sources.fundamentals.yahoo_finance import YahooFinanceFundamentalsAdapter
from src.database.models.company import Company
from src.database.models.fundamentals import FinancialStatementItem, FinancialStatementRaw
from src.database.models.mixins import QualityStatus
from src.database.session import make_engine
from src.ingestion.fundamentals import ingest_fundamentals

pytestmark = pytest.mark.integration

_FIXTURE_TICKER = "ZZZFUNDBBCA"  # never a real ticker -- see module docstring


@pytest.fixture()
def db_session():
    engine = make_engine("postgresql+psycopg://idx:idx@localhost:5433/idx_intelligence")
    with Session(engine) as session:
        yield session
        session.rollback()


@pytest.fixture()
def fixture_company(db_session):
    """A disposable Company row real ingestion/cleanup can freely mutate,
    decoupled from any real ticker's production data."""
    company = Company(ticker=_FIXTURE_TICKER, company_name="Test Fixture BBCA-shadow Co")
    db_session.add(company)
    db_session.commit()
    yield company
    db_session.query(FinancialStatementItem).filter(FinancialStatementItem.company_id == company.id).delete()
    db_session.query(FinancialStatementRaw).filter(FinancialStatementRaw.company_id == company.id).delete()
    db_session.query(Company).filter(Company.id == company.id).delete()
    db_session.commit()


def _real_bbca_provider() -> YahooFinanceFundamentalsAdapter:
    # Fetches real Yahoo data for the real BBCA.JK symbol regardless of
    # which (fixture) ticker string the caller passes to ingest_fundamentals.
    return YahooFinanceFundamentalsAdapter(symbol_resolver=lambda _ticker: "BBCA.JK")


class _FakeFundamentalsProvider(FundamentalsProvider):
    """Deterministic stand-in for testing ingest_fundamentals's own logic
    (completeness/quality_status) without depending on which real period
    happens to be sparse on Yahoo's live data at test time."""

    def __init__(self, documents: dict[str, dict[str, float]]) -> None:
        self._documents = documents  # fiscal_period -> line_items
        self._source = SourceDescriptor(name="fake_fundamentals", url="https://example.invalid", access_type=AccessType.FALLBACK_PROVIDER)

    @property
    def provider_name(self) -> str:
        return "fake_fundamentals"

    def list_available_statements(self, ticker: str, since: dt.date) -> SourcedValue[list[str]]:
        now = dt.datetime.now(dt.UTC)
        return SourcedValue(
            value=list(self._documents),
            source=self._source,
            retrieved_at=now,
            available_at=now,
            period_start=since,
            period_end=None,
            validation_status=ValidationStatus.VALID,
        )

    def get_statement(self, ticker: str, fiscal_period: str) -> SourcedValue[FinancialStatementDocument]:
        now = dt.datetime.now(dt.UTC)
        doc = FinancialStatementDocument(
            company_ticker=ticker,
            statement_type="annual",
            fiscal_period=fiscal_period,
            source_format="json_csv_xlsx",
            currency="IDR",
            scale="unit",
            line_items=self._documents[fiscal_period],
        )
        return SourcedValue(
            value=doc,
            source=self._source,
            retrieved_at=now,
            available_at=now,
            period_start=None,
            period_end=dt.date(2025, 12, 31),
            validation_status=ValidationStatus.VALID,
        )


def test_ingest_fundamentals_bbca_writes_real_statements(db_session, fixture_company):
    provider = _real_bbca_provider()
    run_uuid = str(uuid.uuid4())
    outcome = ingest_fundamentals(db_session, provider, _FIXTURE_TICKER, run_uuid)
    db_session.commit()

    assert outcome.skipped_reason is None
    assert outcome.statements_written > 0
    assert outcome.items_written > 0

    raws = db_session.scalars(
        select(FinancialStatementRaw).where(FinancialStatementRaw.company_id == fixture_company.id)
    ).all()
    assert len(raws) == outcome.statements_written
    assert all(r.statement_currency == "IDR" for r in raws)
    assert all(r.period_end is not None for r in raws)
    # available_at must be strictly after period_end -- point-in-time
    # discipline, not the period_end == available_at leakage bug.
    assert all(r.available_at.date() > r.period_end for r in raws)

    items = db_session.scalars(
        select(FinancialStatementItem).where(FinancialStatementItem.company_id == fixture_company.id)
    ).all()
    assert len(items) == outcome.items_written
    assert all(item.account_code in ACCOUNT_CODE_SECTIONS for item in items)
    assert all(item.statement_section == ACCOUNT_CODE_SECTIONS[item.account_code] for item in items)

    net_income_items = [item for item in items if item.account_code == "net_income"]
    assert net_income_items
    assert all(float(item.value) > 0 for item in net_income_items)  # BBCA has been consistently profitable

    # BBCA's real statements are reasonably complete (~20-24 of 30
    # codes each, live-checked) -- none should fall below the
    # completeness threshold and be marked INSUFFICIENT.
    assert all(r.quality_status == QualityStatus.VALID for r in raws)


def test_ingest_fundamentals_is_idempotent_on_rerun(db_session, fixture_company):
    provider = _real_bbca_provider()
    first = ingest_fundamentals(db_session, provider, _FIXTURE_TICKER, str(uuid.uuid4()))
    db_session.commit()
    second = ingest_fundamentals(db_session, provider, _FIXTURE_TICKER, str(uuid.uuid4()))
    db_session.commit()

    assert second.statements_written == first.statements_written
    raws = db_session.scalars(
        select(FinancialStatementRaw).where(FinancialStatementRaw.company_id == fixture_company.id)
    ).all()
    # clear-then-rewrite: must not accumulate duplicate rows per rerun
    assert len(raws) == first.statements_written


def test_ingest_fundamentals_unknown_ticker_is_skipped(db_session):
    provider = YahooFinanceFundamentalsAdapter()
    outcome = ingest_fundamentals(db_session, provider, "NOPE_NOT_REAL", str(uuid.uuid4()))
    assert outcome.skipped_reason is not None
    assert outcome.statements_written == 0


def test_sparse_statement_is_marked_insufficient_not_dropped(db_session, fixture_company):
    # 2 of 30 taxonomy codes populated (~6.7%) -- below the 20% threshold.
    # Must still be WRITTEN (real numbers, not fabricated) but flagged,
    # not silently kept at the same VALID status as a full statement.
    provider = _FakeFundamentalsProvider({"2025FY": {"net_income": 1000.0, "total_assets": 5000.0}})
    outcome = ingest_fundamentals(db_session, provider, _FIXTURE_TICKER, str(uuid.uuid4()))
    db_session.commit()

    assert outcome.statements_written == 1
    assert outcome.items_written == 2

    raw = db_session.scalar(
        select(FinancialStatementRaw).where(FinancialStatementRaw.company_id == fixture_company.id)
    )
    assert raw.quality_status == QualityStatus.INSUFFICIENT
    assert raw.raw_payload["n_items"] == 2

    items = db_session.scalars(
        select(FinancialStatementItem).where(FinancialStatementItem.company_id == fixture_company.id)
    ).all()
    assert len(items) == 2  # real values kept, not discarded
    assert all(item.quality_status == QualityStatus.INSUFFICIENT for item in items)


def test_complete_enough_statement_is_marked_valid(db_session, fixture_company):
    # 7 of 30 codes (~23%) -- just above the 20% threshold.
    line_items = {code: float(i + 1) for i, code in enumerate(list(ACCOUNT_CODE_SECTIONS)[:7])}
    provider = _FakeFundamentalsProvider({"2025FY": line_items})
    ingest_fundamentals(db_session, provider, _FIXTURE_TICKER, str(uuid.uuid4()))
    db_session.commit()

    raw = db_session.scalar(
        select(FinancialStatementRaw).where(FinancialStatementRaw.company_id == fixture_company.id)
    )
    assert raw.quality_status == QualityStatus.VALID
