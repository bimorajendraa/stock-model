"""CLI command implementations for valuation (spec section 8/10)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.cli.batch import BatchRunner, select_companies
from src.cli.market import _finish_pipeline_run, _start_pipeline_run
from src.config.settings import Settings
from src.database.models.fundamentals import FinancialRatio
from src.database.models.ml import ValuationResult
from src.valuation.pipeline import ValuationAssumptions, compute_valuation


def cmd_valuation_compute(
    session: Session,
    settings: Settings,
    offset: int = 0,
    limit: int | None = None,
    tickers: list[str] | None = None,
    sector: str | None = None,
    all_: bool = False,
    only_missing: bool = False,
    only_eligible: bool = False,
    retry_deferred: bool = False,
) -> int:
    pipeline_name = "valuation_compute"
    run = _start_pipeline_run(session, pipeline_name)
    companies = select_companies(
        session,
        tickers=tickers,
        sector=sector,
        offset=offset,
        limit=limit,
        all_=all_,
        # eligible = has fundamental ratios to value against -- the real prerequisite compute_valuation itself needs
        only_eligible_stmt=select(FinancialRatio.company_id).distinct() if only_eligible else None,
        only_missing_stmt=select(ValuationResult.company_id).distinct() if only_missing else None,
        defer_attempts_for_pipeline=(pipeline_name if only_missing and not retry_deferred else None),
    )
    if not companies:
        if only_missing:
            _finish_pipeline_run(session, run, 0, 0, None)
            print("Nothing to do: all missing companies are complete or waiting for retry_after.")
            return 0
        _finish_pipeline_run(session, run, 0, 0, "no companies selected")
        print(
            "FAILED: no companies selected (check --tickers/--sector/--offset/--limit, or --only-missing/--only-eligible found nothing left to do)."
        )
        return 1

    batch = BatchRunner(pipeline_name=pipeline_name, pipeline_run_id=run.id)
    assumptions = ValuationAssumptions(
        discount_rate=settings.dcf_discount_rate,
        near_term_growth_rate=settings.dcf_near_term_growth_rate,
        terminal_growth_rate=settings.dcf_terminal_growth_rate,
        projection_years=settings.dcf_projection_years,
    )

    for company in companies:
        outcome = batch.run(
            session,
            company.ticker,
            compute_valuation,
            session,
            company.ticker,
            assumptions=assumptions,
            company_id=company.id,
        )
        session.commit()
        if outcome is None:
            continue
        if outcome.skipped_reason:
            batch.skipped += 1
            print(f"{company.ticker}: SKIPPED ({outcome.skipped_reason})")
            continue
        print(f"{company.ticker}: methods={list(outcome.methods_used)} as_of={outcome.as_of_date}")
        batch.written += 1

    _finish_pipeline_run(
        session,
        run,
        batch.written,
        batch.skipped + batch.failed,
        None,
        batch.failure_summary(),
    )
    print(
        f"\nValuation-compute summary: {len(companies)} companies, {batch.written} written, "
        f"{batch.skipped} skipped, {batch.failed} failed"
    )
    return 1 if batch.failed else 0
