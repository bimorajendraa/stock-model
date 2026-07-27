"""CLI command implementations for fundamentals ingestion (spec section 3.3)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.cli.batch import BatchRunner, select_companies
from src.cli.market import _finish_pipeline_run, _start_pipeline_run
from src.config.settings import Settings
from src.data_sources.fundamentals.base import FundamentalsProvider
from src.data_sources.fundamentals.idx_xbrl import IDXOfficialXBRLArchiveAdapter
from src.data_sources.fundamentals.selector import PriorityFundamentalsProvider
from src.data_sources.fundamentals.yahoo_finance import YahooFinanceFundamentalsAdapter
from src.database.models.fundamentals import FinancialStatementRaw
from src.ingestion.fundamentals import ingest_fundamentals


def build_fundamentals_provider(settings: Settings) -> FundamentalsProvider:
    fallback = YahooFinanceFundamentalsAdapter()
    if settings.fundamentals_provider == "yahoo_finance":
        return fallback
    if settings.fundamentals_provider not in {"auto", "idx_xbrl"}:
        raise ValueError("FUNDAMENTALS_PROVIDER must be auto, idx_xbrl, or yahoo_finance")
    if not settings.idx_xbrl_manifest_path:
        if settings.fundamentals_provider == "idx_xbrl":
            raise ValueError("IDX_XBRL_MANIFEST_PATH is required for FUNDAMENTALS_PROVIDER=idx_xbrl")
        return fallback
    official = IDXOfficialXBRLArchiveAdapter(settings.idx_xbrl_manifest_path)
    return official if settings.fundamentals_provider == "idx_xbrl" else PriorityFundamentalsProvider(official, fallback)


def cmd_fundamentals_sync(
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
    pipeline_name = "fundamentals_sync"
    # Validate provider configuration before creating a durable "running"
    # pipeline row, so a missing official manifest cannot leave a stale run.
    provider = build_fundamentals_provider(settings)
    run = _start_pipeline_run(session, pipeline_name)
    companies = select_companies(
        session,
        tickers=tickers,
        sector=sector,
        offset=offset,
        limit=limit,
        all_=all_,
        only_missing_stmt=select(FinancialStatementRaw.company_id).distinct() if only_missing else None,
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
            ingest_fundamentals,
            session,
            provider,
            company.ticker,
            run.run_uuid,
            company_id=company.id,
        )
        session.commit()
        if outcome is None:
            continue
        if outcome.skipped_reason:
            batch.skipped += 1
            print(f"{company.ticker}: SKIPPED ({outcome.skipped_reason})")
            continue
        print(f"{company.ticker}: statements={outcome.statements_written} items={outcome.items_written}")
        batch.written += outcome.statements_written

    _finish_pipeline_run(
        session,
        run,
        batch.written,
        batch.skipped + batch.failed,
        None,
        batch.failure_summary(),
    )
    print(
        f"\nFundamentals-sync summary: {len(companies)} companies, {batch.written} statements written, "
        f"{batch.skipped} skipped, {batch.failed} failed"
    )
    return 1 if batch.failed else 0
