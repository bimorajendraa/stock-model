"""CLI command implementations for feature engineering (spec section 7)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.cli.batch import BatchRunner, select_companies
from src.cli.market import _finish_pipeline_run, _start_pipeline_run
from src.config.settings import Settings
from src.database.models.features import TechnicalFeature
from src.database.models.fundamentals import FinancialRatio, FinancialStatementRaw
from src.database.models.mixins import QualityStatus
from src.features.fundamentals.pipeline import compute_fundamental_ratios
from src.features.technical.pipeline import compute_technical_features


def cmd_features_compute_technical(
    session: Session,
    settings: Settings,
    offset: int = 0,
    limit: int | None = None,
    tickers: list[str] | None = None,
    sector: str | None = None,
    all_: bool = False,
    only_missing: bool = False,
    retry_deferred: bool = False,
) -> int:
    pipeline_name = "features_compute_technical"
    run = _start_pipeline_run(session, pipeline_name)
    companies = select_companies(
        session,
        tickers=tickers,
        sector=sector,
        offset=offset,
        limit=limit,
        all_=all_,
        only_missing_stmt=select(TechnicalFeature.company_id).distinct() if only_missing else None,
        defer_attempts_for_pipeline=(pipeline_name if only_missing and not retry_deferred else None),
    )
    if not companies:
        if only_missing:
            _finish_pipeline_run(session, run, 0, 0, None)
            print("Nothing to do: all missing companies are complete or waiting for retry_after.")
            return 0
        _finish_pipeline_run(session, run, 0, 0, "no companies selected")
        print(
            "FAILED: no companies selected (check --tickers/--sector/--offset/--limit, or --only-missing found nothing left to do)."
        )
        return 1

    batch = BatchRunner(pipeline_name=pipeline_name, pipeline_run_id=run.id)

    for company in companies:
        outcome = batch.run(
            session,
            company.ticker,
            compute_technical_features,
            session,
            company.ticker,
            company_id=company.id,
        )
        session.commit()
        if outcome is None:
            continue  # batch.run already printed/recorded the failure
        if outcome.skipped_reason:
            batch.skipped += 1
            continue
        print(f"{company.ticker}: dates={outcome.dates_processed} rows_written={outcome.rows_written}")
        batch.written += outcome.rows_written

    _finish_pipeline_run(
        session,
        run,
        batch.written,
        batch.skipped + batch.failed,
        None,
        batch.failure_summary(),
    )
    print(
        f"\nCompute-technical summary: {len(companies)} companies, {batch.written} feature rows written, "
        f"{batch.skipped} skipped (no clean price data), {batch.failed} failed"
    )
    return 1 if batch.failed else 0


def cmd_features_compute_fundamental_ratios(
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
    pipeline_name = "features_compute_fundamental_ratios"
    run = _start_pipeline_run(session, pipeline_name)
    companies = select_companies(
        session,
        tickers=tickers,
        sector=sector,
        offset=offset,
        limit=limit,
        all_=all_,
        only_missing_stmt=select(FinancialRatio.company_id).distinct() if only_missing else None,
        only_eligible_stmt=(
            select(FinancialStatementRaw.company_id)
            .where(FinancialStatementRaw.quality_status != QualityStatus.INSUFFICIENT)
            .distinct()
            if only_eligible
            else None
        ),
        defer_attempts_for_pipeline=(pipeline_name if only_missing and not retry_deferred else None),
    )
    if not companies:
        if only_missing:
            _finish_pipeline_run(session, run, 0, 0, None)
            print("Nothing to do: all missing companies are complete or waiting for retry_after.")
            return 0
        _finish_pipeline_run(session, run, 0, 0, "no companies selected")
        print(
            "FAILED: no companies selected (check --tickers/--sector/--offset/--limit, "
            "or --only-missing/--only-eligible found nothing left to do)."
        )
        return 1

    batch = BatchRunner(pipeline_name=pipeline_name, pipeline_run_id=run.id)

    for company in companies:
        outcome = batch.run(
            session,
            company.ticker,
            compute_fundamental_ratios,
            session,
            company.ticker,
            company_id=company.id,
        )
        session.commit()
        if outcome is None:
            continue
        if outcome.skipped_reason:
            batch.skipped += 1
            print(f"{company.ticker}: SKIPPED ({outcome.skipped_reason})")
            continue
        print(f"{company.ticker}: statements={outcome.statements_processed} ratios={outcome.ratios_written}")
        batch.written += outcome.ratios_written

    _finish_pipeline_run(
        session,
        run,
        batch.written,
        batch.skipped + batch.failed,
        None,
        batch.failure_summary(),
    )
    print(
        f"\nCompute-fundamental-ratios summary: {len(companies)} companies, {batch.written} ratio rows written, "
        f"{batch.skipped} skipped, {batch.failed} failed"
    )
    return 1 if batch.failed else 0
