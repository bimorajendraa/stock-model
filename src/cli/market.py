"""CLI command implementations for market-data operations (spec section 13).

Every command records a ``pipeline_runs`` row (run_uuid doubles as
``ingestion_run_id`` for lineage) and returns a process exit code -- 0 on
success, non-zero if anything failed, per spec: "Command harus
mengembalikan exit code non-zero apabila gagal."
"""
from __future__ import annotations

import datetime as dt
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.data_sources.market.capability import ProviderAccessError
from src.data_sources.market.selector import MarketDataProviderSelector, NoLicensedProviderAvailableError
from src.data_sources.market.twelve_data import TwelveDataMarketProvider
from src.data_sources.market.yahoo_finance import YahooFinanceOHLCVAdapter
from src.database.models.company import Company
from src.database.models.market import MarketPriceRaw
from src.database.models.ops import PipelineRun
from src.ingestion.corporate_actions import ingest_corporate_actions
from src.ingestion.incremental import backfill_window, update_window
from src.ingestion.market_data import ingest_ohlcv
from src.ingestion.reconciliation import reconcile_and_store
from src.ingestion.resilience import CircuitBreaker, RateLimiter
from src.preprocessing.market_prices import build_clean_prices

logger = logging.getLogger(__name__)


def build_selector(settings: Settings) -> MarketDataProviderSelector:
    twelve_data = TwelveDataMarketProvider(api_key=settings.twelve_data_api_key)
    yahoo = YahooFinanceOHLCVAdapter()
    return MarketDataProviderSelector(
        twelve_data_provider=twelve_data,
        yahoo_provider=yahoo,
        twelve_data_api_key=settings.twelve_data_api_key,
        configured_provider=settings.market_data_provider,
        usage_mode=settings.market_data_usage_mode,
        enable_yahoo_fallback=settings.enable_yahoo_finance_fallback,
    )


def _probe_ticker(session: Session) -> str | None:
    preferred = session.scalar(select(Company).where(Company.ticker == "BBCA"))
    if preferred is not None:
        return preferred.ticker
    any_company = session.scalar(select(Company).order_by(Company.ticker))
    return any_company.ticker if any_company else None


def _select_companies(session: Session, count: int) -> list[Company]:
    """Deterministic spread across the ticker alphabet, not a hardcoded
    list -- pulled live from whatever's actually in the database. Not a
    genuine sector-diversity or listing-history-length selection: neither
    adapter provides sector or listing_date data yet (see
    docs/data_sources.md's company-master-data limitation), so an even
    spread across tickers is the best proxy available without that
    metadata."""
    all_companies = list(session.scalars(select(Company).order_by(Company.ticker)))
    if not all_companies:
        return []
    if count >= len(all_companies):
        return all_companies
    step = len(all_companies) / count
    return [all_companies[int(i * step)] for i in range(count)]


def _start_pipeline_run(session: Session, pipeline_name: str) -> PipelineRun:
    run = PipelineRun(
        run_uuid=str(uuid.uuid4()),
        pipeline_name=pipeline_name,
        status="running",
        started_at=dt.datetime.now(dt.UTC),
    )
    session.add(run)
    session.flush()
    return run


def _finish_pipeline_run(session: Session, run: PipelineRun, records_in: int, records_failed: int, error: str | None) -> None:
    run.status = "failed" if error else ("partial" if records_failed else "succeeded")
    run.completed_at = dt.datetime.now(dt.UTC)
    run.records_in = records_in
    run.records_failed = records_failed
    run.error_message = error
    session.commit()


def cmd_providers_check(session: Session, settings: Settings) -> int:
    selector = build_selector(settings)
    ticker = _probe_ticker(session)
    if ticker is None:
        print("No companies in database -- run `market sync-companies` (Tahap 2 company sync) first.")
        return 1

    print(f"Probing market data providers using ticker={ticker} ...")
    try:
        provider, capability = selector.select(ticker)
    except (ProviderAccessError, NoLicensedProviderAvailableError) as exc:
        print(f"FAILED: no usable provider. {exc}")
        return 1

    print(f"Selected provider: {provider.provider_name}")
    print(f"  status={capability.status}")
    print(f"  access_level={capability.access_level}")
    print(f"  is_official={capability.is_official}")
    print(f"  supports_commercial_use={capability.supports_commercial_use}")
    if capability.failure_reason:
        print(f"  failure_reason={capability.failure_reason}")
    return 0


def _ingest_one_ticker(
    session: Session,
    selector: MarketDataProviderSelector,
    settings: Settings,
    ticker: str,
    run_uuid: str,
    rate_limiter: RateLimiter,
    breaker: CircuitBreaker,
    window: tuple[dt.date, dt.date],
) -> tuple[int, int, int]:
    """Returns (fetched, written, quarantined)."""
    breaker.check()
    rate_limiter.wait()
    try:
        provider, capability = selector.select(ticker)
    except (ProviderAccessError, NoLicensedProviderAvailableError) as exc:
        breaker.record_failure()
        logger.error("provider_selection_failed", extra={"ticker": ticker, "error": str(exc)})
        return 0, 0, 0

    start, end = window
    outcome = ingest_ohlcv(
        session, provider, ticker, start, end, capability, run_uuid, max_retries=settings.ohlcv_max_retries
    )
    if outcome.skipped_reason:
        breaker.record_failure()
        logger.warning("ingest_skipped", extra={"ticker": ticker, "reason": outcome.skipped_reason})
    else:
        breaker.record_success()
    return outcome.records_fetched, outcome.records_written, outcome.records_quarantined


def cmd_market_smoke_test(session: Session, settings: Settings, count: int) -> int:
    """No fixtures: pulls real tickers from the database and real data from
    whichever provider the capability probe actually selects (spec section
    8). Verifies idempotency by re-running ingestion and checking the row
    count doesn't grow."""
    run = _start_pipeline_run(session, "market_smoke_test")
    selector = build_selector(settings)
    companies = _select_companies(session, count)
    if not companies:
        _finish_pipeline_run(session, run, 0, 0, "no companies in database")
        print("FAILED: no companies in database.")
        return 1

    rate_limiter = RateLimiter(settings.ohlcv_request_delay_seconds)
    breaker = CircuitBreaker(failure_threshold=max(3, count))
    total_written = 0
    total_failed = 0
    per_ticker_first_run: dict[str, int] = {}

    for company in companies:
        window = backfill_window(company.listing_date)
        fetched, written, quarantined = _ingest_one_ticker(
            session, selector, settings, company.ticker, run.run_uuid, rate_limiter, breaker, window
        )
        session.commit()
        per_ticker_first_run[company.ticker] = written
        print(f"{company.ticker}: fetched={fetched} written={written} quarantined={quarantined}")
        if written == 0 and fetched == 0:
            total_failed += 1
        total_written += written

    # Idempotency check: re-run the same window for the same tickers, confirm no row-count growth.
    print("\nRe-running for idempotency check ...")
    idempotent_ok = True
    for company in companies:
        count_before = len(
            list(session.scalars(select(MarketPriceRaw).where(MarketPriceRaw.company_id == company.id)))
        )
        window = backfill_window(company.listing_date)
        _ingest_one_ticker(session, selector, settings, company.ticker, run.run_uuid, rate_limiter, breaker, window)
        session.commit()
        count_after = len(
            list(session.scalars(select(MarketPriceRaw).where(MarketPriceRaw.company_id == company.id)))
        )
        if count_after != count_before:
            idempotent_ok = False
            print(f"  IDEMPOTENCY FAILURE for {company.ticker}: {count_before} -> {count_after} rows")

    _finish_pipeline_run(session, run, total_written, total_failed, None if idempotent_ok else "idempotency check failed")

    print(f"\nSmoke test summary: {len(companies)} tickers, {total_written} rows written, idempotent={idempotent_ok}")
    return 0 if idempotent_ok and total_failed == 0 else 1


def cmd_market_backfill(
    session: Session,
    settings: Settings,
    count: int | None,
    ticker: str | None,
    offset: int = 0,
    limit: int | None = None,
) -> int:
    run = _start_pipeline_run(session, "market_backfill")
    selector = build_selector(settings)
    if ticker:
        companies = [c for c in [session.scalar(select(Company).where(Company.ticker == ticker))] if c]
    elif offset or limit is not None:
        # Plain ticker-ordered slice, not the spread sampling _select_companies
        # does for smoke tests -- used to chunk a full-universe backfill into
        # pieces that each finish within a single process run.
        all_companies = list(session.scalars(select(Company).order_by(Company.ticker)))
        companies = all_companies[offset : offset + limit] if limit is not None else all_companies[offset:]
    else:
        companies = _select_companies(session, count or 50)
    if not companies:
        _finish_pipeline_run(session, run, 0, 0, "no matching companies")
        print("FAILED: no matching companies.")
        return 1

    rate_limiter = RateLimiter(settings.ohlcv_request_delay_seconds)
    breaker = CircuitBreaker(failure_threshold=10)
    total_written = 0
    total_failed = 0

    for company in companies:
        window = backfill_window(company.listing_date)
        try:
            fetched, written, quarantined = _ingest_one_ticker(
                session, selector, settings, company.ticker, run.run_uuid, rate_limiter, breaker, window
            )
        except Exception as exc:  # noqa: BLE001 -- batch loop: one ticker's failure (incl. circuit breaker open) must not crash the whole run
            print(f"{company.ticker}: STOPPED ({exc})")
            total_failed += 1
            break
        session.commit()
        print(f"{company.ticker}: fetched={fetched} written={written} quarantined={quarantined}")
        if written == 0 and fetched == 0:
            total_failed += 1
        total_written += written

    _finish_pipeline_run(session, run, total_written, total_failed, None)
    print(f"\nBackfill summary: {len(companies)} tickers, {total_written} rows written, {total_failed} failed")
    return 0 if total_failed == 0 else 1


def cmd_market_update(session: Session, settings: Settings) -> int:
    run = _start_pipeline_run(session, "market_update")
    selector = build_selector(settings)
    companies = list(session.scalars(select(Company).order_by(Company.ticker)))
    rate_limiter = RateLimiter(settings.ohlcv_request_delay_seconds)
    breaker = CircuitBreaker(failure_threshold=10)
    total_written = 0
    total_failed = 0

    for company in companies:
        last_row = session.scalar(
            select(MarketPriceRaw)
            .where(MarketPriceRaw.company_id == company.id)
            .order_by(MarketPriceRaw.trade_date.desc())
        )
        last_date = last_row.trade_date if last_row else None
        window = update_window(last_date, company.listing_date)
        try:
            fetched, written, quarantined = _ingest_one_ticker(
                session, selector, settings, company.ticker, run.run_uuid, rate_limiter, breaker, window
            )
        except Exception as exc:  # noqa: BLE001 -- batch loop: one ticker's failure must not crash the whole run
            print(f"{company.ticker}: STOPPED ({exc})")
            total_failed += 1
            break
        session.commit()
        if written or fetched:
            print(f"{company.ticker}: fetched={fetched} written={written} quarantined={quarantined}")
        if written == 0 and fetched == 0:
            total_failed += 1
        total_written += written

    _finish_pipeline_run(session, run, total_written, total_failed, None)
    print(f"\nUpdate summary: {len(companies)} tickers, {total_written} rows written, {total_failed} failed")
    return 0 if total_failed == 0 else 1


def cmd_corporate_actions_sync(session: Session, settings: Settings, ticker: str) -> int:
    run = _start_pipeline_run(session, "corporate_actions_sync")
    selector = build_selector(settings)
    try:
        provider, _capability = selector.select(ticker)
    except (ProviderAccessError, NoLicensedProviderAvailableError) as exc:
        _finish_pipeline_run(session, run, 0, 1, str(exc))
        print(f"FAILED: {exc}")
        return 1

    start, end = backfill_window(None)
    outcome = ingest_corporate_actions(session, provider, ticker, start, end, max_retries=settings.ohlcv_max_retries)
    session.commit()
    _finish_pipeline_run(session, run, outcome.records_written, 0 if not outcome.skipped_reason else 1, outcome.skipped_reason)

    if outcome.skipped_reason:
        print(f"FAILED: {outcome.skipped_reason}")
        return 1
    print(f"{ticker}: fetched={outcome.records_fetched} written={outcome.records_written} (provider={provider.provider_name})")
    return 0


def cmd_market_reconcile(session: Session, settings: Settings, count: int) -> int:
    """Cross-checks Twelve Data vs. Yahoo Finance closes for the latest
    common trading date, for N companies -- see reconciliation module
    docstring for why this isn't literally IDX."""
    run = _start_pipeline_run(session, "market_reconcile")
    companies = _select_companies(session, count)
    if not companies:
        _finish_pipeline_run(session, run, 0, 0, "no companies in database")
        print("FAILED: no companies in database.")
        return 1

    twelve_data = TwelveDataMarketProvider(api_key=settings.twelve_data_api_key)
    yahoo = YahooFinanceOHLCVAdapter()
    rate_limiter = RateLimiter(settings.ohlcv_request_delay_seconds)

    checked = 0
    for company in companies:
        rate_limiter.wait()
        end = dt.datetime.now(dt.UTC).date()
        start = end - dt.timedelta(days=7)

        try:
            primary = yahoo.get_ohlcv(company.ticker, start, end)
        except Exception as exc:  # noqa: BLE001 -- batch loop: one ticker's failure must not crash the whole run
            print(f"{company.ticker}: primary provider fetch failed, cannot reconcile ({exc})")
            continue
        primary_bar = primary.value[-1] if primary.is_usable() and primary.value else None
        if primary_bar is None:
            print(f"{company.ticker}: no primary data, cannot reconcile")
            continue

        # Verification provider failing is NOT skipped -- it's exactly the
        # verification_unavailable case reconcile_and_store exists to
        # record (spec: store the comparison result, including "couldn't
        # check"), not a reason to silently drop the row.
        try:
            verification = twelve_data.get_ohlcv(company.ticker, start, end)
            verification_bar = verification.value[-1] if verification.is_usable() and verification.value else None
        except Exception as exc:  # noqa: BLE001 -- verification failure must still be recorded, not crash the batch
            print(f"{company.ticker}: verification provider unavailable ({exc})")
            verification_bar = None

        record = reconcile_and_store(
            session,
            company_id=company.id,
            trading_date=primary_bar.trade_date if primary_bar else end,
            primary_provider="yahoo_finance",
            verification_provider="twelve_data",
            primary_close=primary_bar.close if primary_bar else None,
            verification_close=verification_bar.close if verification_bar else None,
            primary_volume=primary_bar.volume if primary_bar else None,
            verification_volume=verification_bar.volume if verification_bar else None,
        )
        session.commit()
        print(f"{company.ticker}: status={record.status} primary={record.primary_close} verification={record.verification_close}")
        checked += 1

    _finish_pipeline_run(session, run, checked, 0, None)
    print(f"\nReconciliation summary: {checked}/{len(companies)} companies checked")
    return 0 if checked > 0 else 1


def cmd_market_build_clean(session: Session, settings: Settings, offset: int = 0, limit: int | None = None) -> int:
    """Preprocesses market_prices_raw -> market_prices_clean (spec section
    6.1) for every company that has raw data, or a chunked slice of them."""
    run = _start_pipeline_run(session, "market_build_clean")
    all_companies = list(session.scalars(select(Company).order_by(Company.ticker)))
    companies = all_companies[offset : offset + limit] if limit is not None else all_companies[offset:]
    if not companies:
        _finish_pipeline_run(session, run, 0, 0, "no companies in database")
        print("FAILED: no companies in database.")
        return 1

    total_written = 0
    total_outliers = 0
    total_skipped = 0

    for company in companies:
        outcome = build_clean_prices(session, company.ticker, settings.price_adjustment_policy)
        session.commit()
        if outcome.skipped_reason:
            total_skipped += 1
            continue
        print(f"{company.ticker}: processed={outcome.rows_processed} written={outcome.rows_written} outliers={outcome.outliers_flagged}")
        total_written += outcome.rows_written
        total_outliers += outcome.outliers_flagged

    _finish_pipeline_run(session, run, total_written, total_skipped, None)
    print(
        f"\nBuild-clean summary: {len(companies)} companies, {total_written} rows written, "
        f"{total_outliers} outliers flagged, {total_skipped} skipped (no raw data)"
    )
    return 0
