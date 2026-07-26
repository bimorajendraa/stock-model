"""CLI command implementations for feature engineering (spec section 7)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.cli.market import _finish_pipeline_run, _start_pipeline_run
from src.config.settings import Settings
from src.database.models.company import Company
from src.features.fundamentals.pipeline import compute_fundamental_ratios
from src.features.technical.pipeline import compute_technical_features


def cmd_features_compute_technical(
    session: Session,
    settings: Settings,
    offset: int = 0,
    limit: int | None = None,
    tickers: list[str] | None = None,
) -> int:
    run = _start_pipeline_run(session, "features_compute_technical")
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
        outcome = compute_technical_features(session, company.ticker)
        session.commit()
        if outcome.skipped_reason:
            total_skipped += 1
            continue
        print(f"{company.ticker}: dates={outcome.dates_processed} rows_written={outcome.rows_written}")
        total_written += outcome.rows_written

    _finish_pipeline_run(session, run, total_written, total_skipped, None)
    print(
        f"\nCompute-technical summary: {len(companies)} companies, {total_written} feature rows written, "
        f"{total_skipped} skipped (no clean price data)"
    )
    return 0


def cmd_features_compute_fundamental_ratios(
    session: Session,
    settings: Settings,
    offset: int = 0,
    limit: int | None = None,
    tickers: list[str] | None = None,
) -> int:
    run = _start_pipeline_run(session, "features_compute_fundamental_ratios")
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
        outcome = compute_fundamental_ratios(session, company.ticker)
        session.commit()
        if outcome.skipped_reason:
            total_skipped += 1
            print(f"{company.ticker}: SKIPPED ({outcome.skipped_reason})")
            continue
        print(
            f"{company.ticker}: statements={outcome.statements_processed} "
            f"ratios={outcome.ratios_written}"
        )
        total_written += outcome.ratios_written

    _finish_pipeline_run(session, run, total_written, total_skipped, None)
    print(
        f"\nCompute-fundamental-ratios summary: {len(companies)} companies, {total_written} ratio rows written, "
        f"{total_skipped} skipped"
    )
    return 0
