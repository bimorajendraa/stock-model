"""Market-data ingestion: provider adapter -> ``market_prices_raw`` (spec §5 step 3).

Deliberately does not adjust for corporate actions, validate OHLC
consistency, or fill missing trading days -- that's ``preprocessing``/
``validation`` (Tahap 2's later steps), which read from ``market_prices_raw``
and write ``market_prices_clean``. This module's only job is: call a
provider, attach lineage, upsert raw rows idempotently.

Assumes company master data is already synced (spec §5 step 2, not yet
implemented) -- a ticker with no matching ``Company`` row is skipped, not
auto-created, so this never invents a company from a ticker string alone.
"""
from __future__ import annotations

import dataclasses
import datetime as dt

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.data_sources.base import ProviderUnavailableError, SourceDescriptor
from src.data_sources.market.base import MarketDataProvider
from src.database.models.company import Company
from src.database.models.market import MarketPriceRaw
from src.database.models.mixins import QualityStatus
from src.database.models.ops import DataSourceRegistry


@dataclasses.dataclass
class IngestOutcome:
    ticker: str
    provider: str
    records_fetched: int = 0
    records_written: int = 0
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


def ingest_ohlcv(
    session: Session,
    provider: MarketDataProvider,
    ticker: str,
    start: dt.date,
    end: dt.date,
) -> IngestOutcome:
    outcome = IngestOutcome(ticker=ticker, provider=provider.provider_name)

    company = session.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        outcome.skipped_reason = "no matching Company row -- run emiten metadata sync first"
        return outcome

    try:
        result = provider.get_ohlcv(ticker, start, end)
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

    source = _get_or_create_source(session, result.source, category="market")

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
        for bar in bars
    ]

    stmt = insert(MarketPriceRaw).values(rows)
    update_cols = {
        col: getattr(stmt.excluded, col)
        for col in (
            "open",
            "high",
            "low",
            "close",
            "volume",
            "transaction_value",
            "transaction_frequency",
            "retrieved_at",
            "available_at",
            "quality_status",
        )
    }
    stmt = stmt.on_conflict_do_update(
        constraint="uq_price_raw_company_date_source",
        set_=update_cols,
    )
    session.execute(stmt)
    outcome.records_written = len(rows)
    return outcome
