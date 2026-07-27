"""CLI command implementations for company sector classification (spec §3.1/§3.5)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.cli.batch import BatchRunner, select_companies
from src.cli.market import _finish_pipeline_run, _start_pipeline_run
from src.config.settings import Settings
from src.database.models.company import Company, SectorRegistry
from src.database.models.fundamentals import FinancialStatementRaw
from src.features.sector.disclosed_pipeline import compute_disclosed_sector_metrics
from src.features.sector.pipeline import compute_sector_relative_metrics
from src.ingestion.resilience import CircuitBreaker, RateLimiter
from src.ingestion.sector_classification import fetch_and_store_sector


def cmd_sector_classify(
    session: Session,
    settings: Settings,
    offset: int = 0,
    limit: int | None = None,
    tickers: list[str] | None = None,
    all_: bool = False,
    only_missing: bool = False,
    retry_deferred: bool = False,
) -> int:
    """Fetches real sector/industry classification via Yahoo Finance for
    a slice of companies -- network-bound, chunk this like backfill for a
    full-universe run."""
    pipeline_name = "sector_classify"
    run = _start_pipeline_run(session, pipeline_name)
    companies = select_companies(
        session,
        tickers=tickers,
        offset=offset,
        limit=limit,
        all_=all_,
        only_missing_stmt=(
            select(Company.id).where(Company.sector_registry_id.is_not(None)) if only_missing else None
        ),
        defer_attempts_for_pipeline=(pipeline_name if only_missing and not retry_deferred else None),
    )
    if not companies:
        if only_missing:
            _finish_pipeline_run(session, run, 0, 0, None)
            print("Nothing to do: all missing companies are complete or waiting for retry_after.")
            return 0
        _finish_pipeline_run(session, run, 0, 0, "no companies in database")
        print("FAILED: no companies in database.")
        return 1

    rate_limiter = RateLimiter(settings.ohlcv_request_delay_seconds)
    breaker = CircuitBreaker(failure_threshold=15)
    batch = BatchRunner(pipeline_name=pipeline_name, pipeline_run_id=run.id)

    for index, company in enumerate(companies):
        if breaker.is_open:
            unprocessed = len(companies) - index
            batch.failed += unprocessed
            batch.failures.append(("batch", f"circuit breaker open; {unprocessed} company(s) not processed"))
            print(f"STOPPED: circuit breaker open; {unprocessed} companies left for --resume")
            break
        rate_limiter.wait()
        outcome = batch.run(
            session,
            company.ticker,
            fetch_and_store_sector,
            session,
            company.ticker,
            company_id=company.id,
        )
        session.commit()
        if outcome is None:
            breaker.record_failure()
            continue
        if outcome.skipped_reason:
            breaker.record_failure()
            batch.skipped += 1
            print(f"{company.ticker}: SKIPPED ({outcome.skipped_reason})")
            continue
        breaker.record_success()
        batch.written += 1
        print(f"{company.ticker}: sector={outcome.sector} industry={outcome.industry}")

    _finish_pipeline_run(
        session,
        run,
        batch.written,
        batch.skipped + batch.failed,
        None,
        batch.failure_summary(),
    )
    print(
        f"\nSector-classify summary: {len(companies)} companies, {batch.written} classified, "
        f"{batch.skipped} skipped, {batch.failed} failed/unprocessed"
    )
    return 1 if batch.failed else 0


def cmd_sector_compute_relative_metrics(session: Session, settings: Settings) -> int:
    """Computes sector-relative percentile-rank metrics for every real
    sector that has classified companies -- DB-only, no network."""
    run = _start_pipeline_run(session, "sector_compute_relative_metrics")
    sectors = list(session.scalars(select(SectorRegistry).order_by(SectorRegistry.sector_code)))
    if not sectors:
        _finish_pipeline_run(session, run, 0, 0, "no sectors in database -- run sector classify first")
        print("FAILED: no sectors in database -- run `sector classify` first.")
        return 1

    total_written = 0
    total_skipped = 0

    for sector in sectors:
        outcome = compute_sector_relative_metrics(session, sector.id)
        session.commit()
        if outcome.skipped_reason:
            total_skipped += 1
            print(f"{sector.sector_name} ({sector.subsector_name}): SKIPPED ({outcome.skipped_reason})")
            continue
        print(
            f"{sector.sector_name} ({sector.subsector_name}): "
            f"companies={outcome.companies_considered} metrics={outcome.metrics_written}"
        )
        total_written += outcome.metrics_written

    _finish_pipeline_run(session, run, total_written, total_skipped, None)
    print(
        f"\nSector-relative-metrics summary: {len(sectors)} sectors, {total_written} metric rows written, {total_skipped} skipped"
    )
    return 0


def cmd_sector_compute_disclosed_metrics(
    session: Session,
    settings: Settings,
    offset: int = 0,
    limit: int | None = None,
    tickers: list[str] | None = None,
    all_: bool = False,
) -> int:
    """Compute bank/mining KPIs from real disclosed filing facts."""
    pipeline_name = "sector_compute_disclosed_metrics"
    run = _start_pipeline_run(session, pipeline_name)
    companies = select_companies(
        session,
        tickers=tickers,
        offset=offset,
        limit=limit,
        all_=all_,
        only_eligible_stmt=select(FinancialStatementRaw.company_id).distinct(),
    )
    if not companies:
        _finish_pipeline_run(session, run, 0, 0, "no companies with financial statements selected")
        return 1

    batch = BatchRunner(pipeline_name=pipeline_name, pipeline_run_id=run.id)
    for company in companies:
        outcome = batch.run(
            session,
            company.ticker,
            compute_disclosed_sector_metrics,
            session,
            company.ticker,
            company_id=company.id,
        )
        session.commit()
        if outcome is None:
            continue
        if outcome.skipped_reason:
            batch.skipped += 1
            continue
        batch.written += outcome.metrics_written
        print(f"{company.ticker}: disclosed_metrics={outcome.metrics_written}")

    _finish_pipeline_run(
        session,
        run,
        batch.written,
        batch.skipped + batch.failed,
        None,
        batch.failure_summary(),
    )
    print(
        f"\nSector-disclosed-metrics summary: {len(companies)} companies, "
        f"{batch.written} metrics written, {batch.skipped} skipped, {batch.failed} failed"
    )
    return 1 if batch.failed else 0
