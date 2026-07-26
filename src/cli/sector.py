"""CLI command implementations for company sector classification (spec §3.1/§3.5)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.cli.market import _finish_pipeline_run, _start_pipeline_run
from src.config.settings import Settings
from src.database.models.company import Company, SectorRegistry
from src.features.sector.pipeline import compute_sector_relative_metrics
from src.ingestion.resilience import CircuitBreaker, RateLimiter
from src.ingestion.sector_classification import fetch_and_store_sector


def cmd_sector_classify(
    session: Session,
    settings: Settings,
    offset: int = 0,
    limit: int | None = None,
    tickers: list[str] | None = None,
) -> int:
    """Fetches real sector/industry classification via Yahoo Finance for
    a slice of companies -- network-bound, chunk this like backfill for a
    full-universe run."""
    run = _start_pipeline_run(session, "sector_classify")
    if tickers:
        companies = [c for c in (session.scalar(select(Company).where(Company.ticker == t)) for t in tickers) if c]
    else:
        all_companies = list(session.scalars(select(Company).order_by(Company.ticker)))
        companies = all_companies[offset : offset + limit] if limit is not None else all_companies[offset:]
    if not companies:
        _finish_pipeline_run(session, run, 0, 0, "no companies in database")
        print("FAILED: no companies in database.")
        return 1

    rate_limiter = RateLimiter(settings.ohlcv_request_delay_seconds)
    breaker = CircuitBreaker(failure_threshold=15)
    total_ok = 0
    total_failed = 0

    for company in companies:
        breaker.check()
        rate_limiter.wait()
        outcome = fetch_and_store_sector(session, company.ticker)
        session.commit()
        if outcome.skipped_reason:
            breaker.record_failure()
            total_failed += 1
            print(f"{company.ticker}: SKIPPED ({outcome.skipped_reason})")
            continue
        breaker.record_success()
        total_ok += 1
        print(f"{company.ticker}: sector={outcome.sector} industry={outcome.industry}")

    _finish_pipeline_run(session, run, total_ok, total_failed, None)
    print(f"\nSector-classify summary: {len(companies)} companies, {total_ok} classified, {total_failed} skipped")
    return 0


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
    print(f"\nSector-relative-metrics summary: {len(sectors)} sectors, {total_written} metric rows written, {total_skipped} skipped")
    return 0
