"""Market-data ingestion: provider adapter -> ``market_prices_raw`` (spec §5
step 3), now capability-aware and validation-gated.

Assumes company master data is already synced (spec §5 step 2) -- a
ticker with no matching ``Company`` row is skipped, not auto-created, so
this never invents a company from a ticker string alone.

Bars that fail OHLCV validation never reach ``market_prices_raw`` -- they
go to ``market_price_quarantine`` instead (spec: "Jangan langsung
menghapus bar yang gagal").
"""
from __future__ import annotations

import dataclasses
import datetime as dt

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.data_sources.base import ProviderUnavailableError, SourceDescriptor
from src.data_sources.market.base import MarketDataProvider
from src.data_sources.market.capability import ProviderCapability
from src.data_sources.market.yahoo_finance import default_yahoo_symbol
from src.database.models.company import Company
from src.database.models.market import MarketPriceQuarantine, MarketPriceRaw
from src.database.models.mixins import QualityStatus
from src.database.models.ops import DataSourceRegistry
from src.ingestion.resilience import with_retry
from src.validation.market_data import validate_ohlcv_bar


@dataclasses.dataclass
class IngestOutcome:
    ticker: str
    provider: str
    records_fetched: int = 0
    records_written: int = 0
    records_quarantined: int = 0
    skipped_reason: str | None = None


def _get_or_create_source(session: Session, descriptor: SourceDescriptor, category: str) -> DataSourceRegistry:
    source = session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == descriptor.name))
    if source is not None:
        return source
    source = DataSourceRegistry(
        name=descriptor.name,
        category=category,
        access_type=descriptor.access_type.value,
        base_url=descriptor.url,
        is_active=True,
    )
    session.add(source)
    session.flush()  # assign source.id without committing
    return source


def _provider_symbol(provider_name: str, ticker: str) -> str:
    if provider_name == "yahoo_finance":
        return default_yahoo_symbol(ticker)
    return ticker


def _usage_restriction(capability: ProviderCapability) -> str:
    # Yahoo Finance is unconditionally research_only (unofficial/ToS-gray
    # source). Twelve Data's actual commercial-redistribution terms for a
    # given plan have not been reviewed by this project, so it is NOT
    # claimed "licensed" just because the capability probe succeeded --
    # "unspecified" is the honest default until someone actually checks
    # the plan's ToS.
    if capability.provider_name == "yahoo_finance":
        return "research_only"
    return "unspecified"


def ingest_ohlcv(
    session: Session,
    provider: MarketDataProvider,
    ticker: str,
    start: dt.date,
    end: dt.date,
    capability: ProviderCapability,
    ingestion_run_id: str,
    max_retries: int = 4,
) -> IngestOutcome:
    outcome = IngestOutcome(ticker=ticker, provider=provider.provider_name)

    company = session.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        outcome.skipped_reason = "no matching Company row -- run emiten metadata sync first"
        return outcome

    try:
        fetch = with_retry(max_retries)(provider.get_ohlcv)
        result = fetch(ticker, start, end)
    except ProviderUnavailableError as exc:
        outcome.skipped_reason = f"provider unavailable: {exc}"
        return outcome

    if not result.is_usable():
        outcome.skipped_reason = f"provider returned no usable data (status={result.validation_status.value})"
        return outcome

    bars = result.value
    outcome.records_fetched = len(bars)
    if not bars:
        return outcome

    today = dt.datetime.now(dt.UTC).date()
    valid_bars = []
    for bar in bars:
        validation = validate_ohlcv_bar(bar, today=today)
        if validation.is_valid:
            valid_bars.append(bar)
        else:
            session.add(
                MarketPriceQuarantine(
                    company_id=company.id,
                    ticker=ticker,
                    provider=provider.provider_name,
                    trade_date=bar.trade_date,
                    raw_row={
                        "trade_date": bar.trade_date.isoformat(),
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                    },
                    validation_errors=validation.errors,
                    ingestion_run_id=ingestion_run_id,
                    found_at=dt.datetime.now(dt.UTC),
                    resolved=False,
                )
            )
            outcome.records_quarantined += 1

    if not valid_bars:
        return outcome

    source = _get_or_create_source(session, result.source, category="market")
    provider_symbol = _provider_symbol(provider.provider_name, ticker)
    usage_restriction = _usage_restriction(capability)

    rows = [
        {
            "company_id": company.id,
            "trade_date": bar.trade_date,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "transaction_value": bar.transaction_value,
            "transaction_frequency": bar.transaction_frequency,
            "adjusted_close_provider": bar.adjusted_close,
            "provider_adjustment_status": bar.provider_adjustment_status,
            "provider_symbol": provider_symbol,
            "exchange": "IDX",
            "interval": "1day",
            "usage_restriction": usage_restriction,
            "verification_status": "provider_reported",
            "adjustment_source": provider.provider_name if bar.adjusted_close is not None else None,
            "ingestion_run_id": ingestion_run_id,
            "source_id": source.id,
            "retrieved_at": result.retrieved_at,
            "available_at": result.available_at,
            "period_start": result.period_start,
            "period_end": result.period_end,
            "currency": "IDR",
            "unit": "unit",
            "is_restated": False,
            "quality_status": QualityStatus.VALID,
        }
        for bar in valid_bars
    ]

    update_col_names = (
        "open",
        "high",
        "low",
        "close",
        "volume",
        "transaction_value",
        "transaction_frequency",
        "adjusted_close_provider",
        "provider_adjustment_status",
        "verification_status",
        "adjustment_source",
        "ingestion_run_id",
        "retrieved_at",
        "available_at",
        "quality_status",
    )

    # Postgres caps bound parameters at 65535 per query. A full 10-year
    # backfill (~2500 rows x 27 columns/row) blows past that in a single
    # multi-row INSERT -- hit live during the Tahap 2 smoke test
    # (psycopg.OperationalError on the 3rd ticker, after two smaller ones
    # succeeded). Chunking keeps each statement comfortably under the
    # limit regardless of how many lineage columns this table grows to.
    chunk_size = 1000
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        stmt = insert(MarketPriceRaw).values(chunk)
        update_cols = {col: getattr(stmt.excluded, col) for col in update_col_names}
        stmt = stmt.on_conflict_do_update(
            constraint="uq_price_raw_company_date_source",
            set_=update_cols,
        )
        session.execute(stmt)

    outcome.records_written = len(rows)
    return outcome
