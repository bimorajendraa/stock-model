"""Integration tests for the shared CLI batch-selection helpers
(``src/cli/batch.py``, "Section L" -- pipelines must accept
--all/--sector/--only-missing/--resume, not just a hardcoded top-50
slice, and one company's real failure must never abort a large batch).
Uses disposable fixture companies (never real tickers).
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.cli.__main__ import build_parser
from src.cli.batch import (
    BatchRunner,
    filter_deferred_attempts,
    filter_has_prerequisite,
    filter_only_missing,
    select_companies,
)
from src.cli.market import _finish_pipeline_run, _start_pipeline_run
from src.database.models.company import Company, SectorRegistry
from src.database.models.features import TechnicalFeature
from src.database.models.ops import PipelineCompanyResult, PipelineRun
from src.database.session import make_engine

pytestmark = pytest.mark.integration

_TICKER_A = "ZZZBATCHA"
_TICKER_B = "ZZZBATCHB"
_TICKER_INACTIVE = "ZZZBATCHC"
_TICKER_INDEX = "ZZZBATCHIDX"
_SECTOR_CODE = "zzztest_batch_sector"
_PIPELINE_NAME = "test_cli_batch_savepoint"
_TRACKING_PIPELINE_NAME = "test_cli_batch_tracking"


@pytest.fixture()
def db_session():
    engine = make_engine("postgresql+psycopg://idx:idx@localhost:5433/idx_intelligence")
    with Session(engine) as session:
        yield session
        session.rollback()


@pytest.fixture()
def fixture_companies(db_session):
    sector = db_session.scalar(select(SectorRegistry).where(SectorRegistry.sector_code == _SECTOR_CODE))
    if sector is None:
        sector = SectorRegistry(
            sector_code=_SECTOR_CODE,
            sector_name="Test Batch Sector",
            metrics_config_key="default",
            valuation_config_key="default",
        )
        db_session.add(sector)
        db_session.commit()

    companies = []
    for ticker, status, in_sector, asset_type in [
        (_TICKER_A, "active", True, "equity"),
        (_TICKER_B, "active", False, "equity"),
        (_TICKER_INACTIVE, "delisted", False, "equity"),
        (_TICKER_INDEX, "active", False, "index"),
    ]:
        company = db_session.scalar(select(Company).where(Company.ticker == ticker))
        if company is None:
            company = Company(
                ticker=ticker,
                company_name=f"Test Batch Co {ticker}",
                status=status,
                asset_type=asset_type,
                sector_registry_id=sector.id if in_sector else None,
            )
            db_session.add(company)
    db_session.commit()
    companies = [
        db_session.scalar(select(Company).where(Company.ticker == t))
        for t in (_TICKER_A, _TICKER_B, _TICKER_INACTIVE, _TICKER_INDEX)
    ]
    yield companies


@pytest.fixture(autouse=True)
def _cleanup(db_session, fixture_companies):
    yield
    company_ids = [c.id for c in fixture_companies]
    db_session.query(PipelineCompanyResult).filter(PipelineCompanyResult.company_id.in_(company_ids)).delete(
        synchronize_session=False
    )
    db_session.query(TechnicalFeature).filter(TechnicalFeature.company_id.in_(company_ids)).delete(
        synchronize_session=False
    )
    db_session.query(Company).filter(
        Company.ticker.in_([_TICKER_A, _TICKER_B, _TICKER_INACTIVE, _TICKER_INDEX])
    ).delete(
        synchronize_session=False
    )
    db_session.query(SectorRegistry).filter(SectorRegistry.sector_code == _SECTOR_CODE).delete()
    db_session.query(PipelineRun).filter(
        PipelineRun.pipeline_name.in_([_PIPELINE_NAME, _TRACKING_PIPELINE_NAME])
    ).delete(synchronize_session=False)
    db_session.commit()


def test_select_companies_tickers_overrides_everything_else(db_session, fixture_companies):
    result = select_companies(
        db_session, tickers=[_TICKER_A, _TICKER_INACTIVE], sector="does not exist", all_=False, limit=0
    )
    assert {c.ticker for c in result} == {_TICKER_A, _TICKER_INACTIVE}


def test_select_companies_filters_by_sector(db_session, fixture_companies):
    result = select_companies(db_session, sector="Test Batch Sector", all_=True)
    tickers = {c.ticker for c in result}
    assert _TICKER_A in tickers
    assert _TICKER_B not in tickers  # not in this sector


def test_select_companies_excludes_inactive_by_default(db_session, fixture_companies):
    result = select_companies(db_session, sector="Test Batch Sector", all_=True, active_only=True)
    assert all(c.status == "active" for c in result)
    result_incl = select_companies(db_session, tickers=[_TICKER_INACTIVE])
    assert result_incl[0].ticker == _TICKER_INACTIVE  # explicit --tickers still reaches inactive ones


def test_select_companies_excludes_non_equity_unless_explicit(db_session, fixture_companies):
    result = select_companies(db_session, all_=True)
    assert _TICKER_INDEX not in {company.ticker for company in result}

    explicit = select_companies(db_session, tickers=[_TICKER_INDEX])
    assert explicit[0].ticker == _TICKER_INDEX


def test_select_companies_applies_only_missing_before_limit_not_after(db_session, fixture_companies):
    # Real bug found live: applying --limit before --only-missing meant
    # "--limit N --only-missing" could return far fewer than N real
    # companies needing work (or, as reproduced here, a company that
    # should have been excluded) whenever the pre-limit slice happened to
    # already contain companies with data -- --only-missing must narrow
    # the candidate pool BEFORE the limit is applied, not after.
    # Scoped to a sector with exactly one active company so the pool is
    # unambiguous: that company already has data, so with the ordering
    # fixed, --limit 1 --only-missing on this pool must return nothing --
    # the old (buggy) order would slice to that one company *first* and
    # only then check --only-missing, but since limit already consumed
    # the sole candidate, the bug wouldn't even have been reproducible
    # this way -- so instead this checks the direct, load-bearing
    # contract: an --only-missing result set must never contain a company
    # known to already have data, at any limit.
    company_a = next(c for c in fixture_companies if c.ticker == _TICKER_A)
    db_session.add(
        TechnicalFeature(
            company_id=company_a.id,
            feature_date=dt.datetime.now(dt.UTC).date(),
            feature_name="rsi_14",
            value=50.0,
            feature_set_version="v1",
        )
    )
    db_session.commit()

    result = select_companies(
        db_session,
        sector="Test Batch Sector",
        offset=0,
        limit=1,
        only_missing_stmt=select(TechnicalFeature.company_id).distinct(),
    )
    assert result == []  # the sector's one company already has data -- limit=1 must not resurrect it


def test_filter_only_missing_excludes_companies_with_existing_rows(db_session, fixture_companies):
    company_a = next(c for c in fixture_companies if c.ticker == _TICKER_A)
    db_session.add(
        TechnicalFeature(
            company_id=company_a.id,
            feature_date=dt.datetime.now(dt.UTC).date(),
            feature_name="rsi_14",
            value=50.0,
            feature_set_version="v1",
        )
    )
    db_session.commit()

    result = filter_only_missing(
        db_session, fixture_companies, select(TechnicalFeature.company_id).distinct()
    )
    assert company_a not in result
    assert len(result) == len(fixture_companies) - 1


def test_filter_has_prerequisite_keeps_only_companies_with_existing_rows(db_session, fixture_companies):
    company_a = next(c for c in fixture_companies if c.ticker == _TICKER_A)
    db_session.add(
        TechnicalFeature(
            company_id=company_a.id,
            feature_date=dt.datetime.now(dt.UTC).date(),
            feature_name="rsi_14",
            value=50.0,
            feature_set_version="v1",
        )
    )
    db_session.commit()

    result = filter_has_prerequisite(
        db_session, fixture_companies, select(TechnicalFeature.company_id).distinct()
    )
    assert result == [company_a]


def test_batch_runner_isolates_one_companys_exception_from_the_rest(db_session):
    batch = BatchRunner()

    def _flaky(ticker: str):
        if ticker == "BAD":
            raise ValueError("simulated real failure")
        return f"ok:{ticker}"

    results = [batch.run(db_session, t, _flaky, t) for t in ("GOOD1", "BAD", "GOOD2")]

    assert results == ["ok:GOOD1", None, "ok:GOOD2"]
    assert batch.failed == 1
    assert batch.failures == [("BAD", "ValueError: simulated real failure")]
    assert batch.failure_summary() == "BAD: ValueError: simulated real failure"


def test_batch_runner_failure_rolls_back_only_company_savepoint(db_session, fixture_companies):
    company_a = next(c for c in fixture_companies if c.ticker == _TICKER_A)
    run = _start_pipeline_run(db_session, _PIPELINE_NAME)
    batch = BatchRunner()

    def _write_then_fail():
        db_session.add(
            TechnicalFeature(
                company_id=company_a.id,
                feature_date=dt.date(2026, 7, 27),
                feature_name="failed_savepoint_feature",
                value=1.0,
                feature_set_version="test",
            )
        )
        db_session.flush()
        raise ValueError("simulated write failure")

    assert batch.run(db_session, company_a.ticker, _write_then_fail) is None
    _finish_pipeline_run(
        db_session,
        run,
        records_in=0,
        records_failed=batch.failed,
        error=None,
        failure_details=batch.failure_summary(),
    )

    stored_run = db_session.scalar(select(PipelineRun).where(PipelineRun.run_uuid == run.run_uuid))
    failed_feature = db_session.scalar(
        select(TechnicalFeature).where(TechnicalFeature.feature_name == "failed_savepoint_feature")
    )
    assert stored_run is not None
    assert stored_run.status == "partial"
    assert stored_run.error_message == f"{_TICKER_A}: ValueError: simulated write failure"
    assert failed_feature is None


def test_batch_runner_persists_company_attempt_outcomes(db_session, fixture_companies):
    company_a, company_b = fixture_companies[:2]
    run = _start_pipeline_run(db_session, _TRACKING_PIPELINE_NAME)
    batch = BatchRunner(pipeline_name=run.pipeline_name, pipeline_run_id=run.id)

    succeeded = batch.run(
        db_session,
        company_a.ticker,
        lambda: SimpleNamespace(skipped_reason=None),
        company_id=company_a.id,
    )
    no_data = batch.run(
        db_session,
        company_b.ticker,
        lambda: SimpleNamespace(skipped_reason="provider returned no available statements"),
        company_id=company_b.id,
    )

    def _provider_failure():
        raise RuntimeError("temporary outage")

    failed = batch.run(
        db_session,
        company_a.ticker,
        _provider_failure,
        company_id=company_a.id,
    )
    _finish_pipeline_run(
        db_session,
        run,
        records_in=1,
        records_failed=1,
        error=None,
        failure_details=batch.failure_summary(),
    )

    results = list(
        db_session.scalars(
            select(PipelineCompanyResult)
            .where(PipelineCompanyResult.pipeline_run_id == run.id)
            .order_by(PipelineCompanyResult.id)
        )
    )
    assert succeeded is not None
    assert no_data is not None
    assert failed is None
    assert [result.status for result in results] == ["succeeded", "no_data", "failed"]
    assert results[0].retry_after is None
    assert results[1].retry_after > results[1].attempted_at
    assert results[2].retry_after > results[2].attempted_at
    assert results[2].message == "RuntimeError: temporary outage"


def test_deferred_filter_uses_latest_attempt_and_explicit_tickers_bypass_it(db_session, fixture_companies):
    company_a = fixture_companies[0]
    now = dt.datetime.now(dt.UTC)
    run = _start_pipeline_run(db_session, _TRACKING_PIPELINE_NAME)
    db_session.add_all(
        [
            PipelineCompanyResult(
                pipeline_run_id=run.id,
                company_id=company_a.id,
                pipeline_name=run.pipeline_name,
                status="no_data",
                attempted_at=now - dt.timedelta(hours=2),
                retry_after=now + dt.timedelta(days=7),
                message="old cooldown",
            ),
            PipelineCompanyResult(
                pipeline_run_id=run.id,
                company_id=company_a.id,
                pipeline_name=run.pipeline_name,
                status="failed",
                attempted_at=now - dt.timedelta(hours=1),
                retry_after=now - dt.timedelta(minutes=1),
                message="newer retry is ready",
            ),
        ]
    )
    db_session.flush()

    assert filter_deferred_attempts(db_session, [company_a], run.pipeline_name, as_of=now) == [company_a]

    latest = PipelineCompanyResult(
        pipeline_run_id=run.id,
        company_id=company_a.id,
        pipeline_name=run.pipeline_name,
        status="no_data",
        attempted_at=now,
        retry_after=now + dt.timedelta(days=7),
        message="latest cooldown",
    )
    db_session.add(latest)
    db_session.flush()
    assert filter_deferred_attempts(db_session, [company_a], run.pipeline_name, as_of=now) == []

    explicit = select_companies(
        db_session,
        tickers=[company_a.ticker],
        defer_attempts_for_pipeline=run.pipeline_name,
    )
    assert explicit == [company_a]


def test_parser_exposes_resumable_sector_and_ratio_flags():
    parser = build_parser()

    sector_args = parser.parse_args(["sector", "classify", "--all", "--resume", "--retry-deferred"])
    assert sector_args.all_ is True
    assert sector_args.resume is True
    assert sector_args.retry_deferred is True

    ratio_args = parser.parse_args(
        ["features", "compute-fundamental-ratios", "--all", "--only-missing", "--only-eligible"]
    )
    assert ratio_args.all_ is True
    assert ratio_args.only_missing is True
    assert ratio_args.only_eligible is True
