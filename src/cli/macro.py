"""CLI command implementations for macro/industry series (spec section 3.4)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from src.cli.market import _finish_pipeline_run, _start_pipeline_run
from src.config.settings import Settings
from src.data_sources.macro.bi_rate import BankIndonesiaJISDORAdapter, BankIndonesiaRateHTMLAdapter
from src.data_sources.macro.bi_seki import BankIndonesiaSEKIInterestRateAdapter
from src.data_sources.macro.bps import BPSMacroAdapter
from src.data_sources.macro.fred import FREDMacroAdapter
from src.data_sources.macro.taxonomy import SERIES_CATALOG
from src.data_sources.macro.world_bank import WorldBankMacroAdapter
from src.data_sources.macro.yahoo_finance import YahooFinanceMacroAdapter
from src.ingestion.macro import ingest_macro_series

_DEFAULT_START = dt.date(2016, 1, 1)  # matches the OHLCV backfill window (docs/market_data.md)


def cmd_macro_sync(session: Session, settings: Settings, series: list[str] | None = None) -> int:
    run = _start_pipeline_run(session, "macro_sync")
    codes = series or list(SERIES_CATALOG)
    unknown = [c for c in codes if c not in SERIES_CATALOG]
    if unknown:
        _finish_pipeline_run(session, run, 0, len(unknown), f"unknown series_code(s): {unknown}")
        print(f"FAILED: unknown series_code(s): {unknown}. Known: {list(SERIES_CATALOG)}")
        return 1

    # Each series is served by exactly one adapter -- route by whichever
    # adapter actually declares it in supported_series(), rather than a
    # separate hardcoded mapping that could drift out of sync.
    providers = [
        YahooFinanceMacroAdapter(),
        BPSMacroAdapter(api_key=settings.bps_api_key),
        BankIndonesiaRateHTMLAdapter(),
        BankIndonesiaJISDORAdapter(),
        WorldBankMacroAdapter(),
        FREDMacroAdapter(api_key=settings.fred_api_key),
        BankIndonesiaSEKIInterestRateAdapter(),
    ]
    provider_for_series = {code: p for p in providers for code in p.supported_series()}

    today = dt.datetime.now(dt.UTC).date()
    total_written = 0
    total_skipped = 0

    for code in codes:
        provider = provider_for_series.get(code)
        if provider is None:
            total_skipped += 1
            print(f"{code}: SKIPPED (no adapter declares this series_code)")
            continue
        outcome = ingest_macro_series(session, provider, code, _DEFAULT_START, today)
        session.commit()
        if outcome.skipped_reason:
            total_skipped += 1
            print(f"{code}: SKIPPED ({outcome.skipped_reason})")
            continue
        print(f"{code} -> {outcome.table}_series: points={outcome.points_written}")
        total_written += outcome.points_written

    _finish_pipeline_run(session, run, total_written, total_skipped, None)
    print(f"\nMacro-sync summary: {len(codes)} series, {total_written} points written, {total_skipped} skipped")
    return 0
