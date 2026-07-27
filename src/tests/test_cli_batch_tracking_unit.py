"""Fast in-memory coverage for per-company batch attempt tracking."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from src.cli.batch import BatchRunner, filter_deferred_attempts
from src.cli.market import _start_pipeline_run
from src.database.models.company import Company, SectorRegistry
from src.database.models.ops import PipelineCompanyResult, PipelineRun


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    for table in (
        SectorRegistry.__table__,
        Company.__table__,
        PipelineRun.__table__,
        PipelineCompanyResult.__table__,
    ):
        table.create(engine)
    with Session(engine) as session:

        @event.listens_for(session, "before_flush")
        def _supply_sqlite_timestamps(session, _flush_context, _instances):
            # Production Postgres understands the project's server_default
            # value; SQLite otherwise returns the literal string "now()".
            now = dt.datetime.now(dt.UTC)
            for obj in session.new:
                if hasattr(obj, "created_at"):
                    obj.created_at = now
                    obj.updated_at = now

        yield session


def _company(session: Session, ticker: str) -> Company:
    company = Company(ticker=ticker, company_name=f"Test {ticker}", status="active")
    session.add(company)
    session.flush()
    return company


def test_runner_records_success_no_data_and_failure(db_session):
    company = _company(db_session, "UNITA")
    run = _start_pipeline_run(db_session, "unit_tracking")
    runner = BatchRunner(pipeline_name=run.pipeline_name, pipeline_run_id=run.id)

    runner.run(
        db_session,
        company.ticker,
        lambda: SimpleNamespace(skipped_reason=None),
        company_id=company.id,
    )
    runner.run(
        db_session,
        company.ticker,
        lambda: SimpleNamespace(skipped_reason="provider returned no data"),
        company_id=company.id,
    )

    def _fail():
        raise RuntimeError("temporary outage")

    assert runner.run(db_session, company.ticker, _fail, company_id=company.id) is None
    db_session.commit()

    results = list(db_session.scalars(select(PipelineCompanyResult).order_by(PipelineCompanyResult.id)))
    assert [result.status for result in results] == ["succeeded", "no_data", "failed"]
    assert results[0].retry_after is None
    assert results[1].retry_after is not None
    assert results[2].message == "RuntimeError: temporary outage"


def test_latest_attempt_controls_retry_cooldown(db_session):
    company = _company(db_session, "UNITB")
    run = _start_pipeline_run(db_session, "unit_retry_filter")
    now = dt.datetime.now(dt.UTC)
    db_session.add_all(
        [
            PipelineCompanyResult(
                pipeline_run_id=run.id,
                company_id=company.id,
                pipeline_name=run.pipeline_name,
                status="no_data",
                attempted_at=now - dt.timedelta(hours=2),
                retry_after=now + dt.timedelta(days=7),
            ),
            PipelineCompanyResult(
                pipeline_run_id=run.id,
                company_id=company.id,
                pipeline_name=run.pipeline_name,
                status="failed",
                attempted_at=now - dt.timedelta(hours=1),
                retry_after=now - dt.timedelta(minutes=1),
            ),
        ]
    )
    db_session.flush()

    assert filter_deferred_attempts(db_session, [company], run.pipeline_name, as_of=now) == [company]

    db_session.add(
        PipelineCompanyResult(
            pipeline_run_id=run.id,
            company_id=company.id,
            pipeline_name=run.pipeline_name,
            status="no_data",
            attempted_at=now,
            retry_after=now + dt.timedelta(days=7),
        )
    )
    db_session.flush()
    assert filter_deferred_attempts(db_session, [company], run.pipeline_name, as_of=now) == []
