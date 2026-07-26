"""CLI command implementations for valuation (spec section 8/10)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.cli.market import _finish_pipeline_run, _start_pipeline_run
from src.config.settings import Settings
from src.database.models.company import Company
from src.valuation.pipeline import compute_valuation


def cmd_valuation_compute(
    session: Session,
    settings: Settings,
    offset: int = 0,
    limit: int | None = None,
    tickers: list[str] | None = None,
) -> int:
    run = _start_pipeline_run(session, "valuation_compute")
    if tickers:
        companies = [c for c in (session.scalar(select(Company).where(Company.ticker == t)) for t in tickers) if c]
    else:
        all_companies = list(session.scalars(select(Company).order_by(Company.ticker)))
        companies = all_companies[offset : offset + limit] if limit is not None else all_companies[offset:]
    if not companies:
        _finish_pipeline_run(session, run, 0, 0, "no companies in database")
        print("FAILED: no companies in database.")
        return 1

    total_written = 0
    total_skipped = 0

    for company in companies:
        outcome = compute_valuation(session, company.ticker)
        session.commit()
        if outcome.skipped_reason:
            total_skipped += 1
            print(f"{company.ticker}: SKIPPED ({outcome.skipped_reason})")
            continue
        print(f"{company.ticker}: methods={list(outcome.methods_used)} as_of={outcome.as_of_date}")
        total_written += 1

    _finish_pipeline_run(session, run, total_written, total_skipped, None)
    print(f"\nValuation-compute summary: {len(companies)} companies, {total_written} written, {total_skipped} skipped")
    return 0
