"""market_prices_raw -> market_prices_clean (spec section 6.1).

Deliberately conservative: never deletes or fills anything on its own
authority.

- Missing trading days are NOT filled. Forward-filling would invent a
  price that never traded (spec §6.1: don't forward-fill past the next
  real value without care) -- a gap in ``market_prices_clean`` for a given
  company/date just means there's no row, not a fabricated flat line.
- Outliers are FLAGGED (``is_outlier_flagged``), never removed (spec:
  "Jangan menghapus outlier pasar secara otomatis sebelum memastikan
  bahwa nilai tersebut bukan kejadian nyata") -- a >35% one-day move on
  IDX is unusual (auto-reject-limit bands are narrower than that for most
  price tiers) but not impossible (IPOs, resumption after suspension,
  genuine crashes), so it stays in the data, just marked for review.
- Adjusted close is resolved via ``PRICE_ADJUSTMENT_POLICY``
  (src/common/price_adjustment.py). With the default
  ``provider_split_adjusted`` policy and no ``officially_verified``
  corporate actions yet (see docs/corporate_actions.md), this resolves to
  the provider's own adjusted close (Yahoo Finance's "Adj Close") for
  every row -- not an internally-verified figure, which the module is
  honest about rather than pretending otherwise.
"""
from __future__ import annotations

import dataclasses
import datetime as dt

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.common.price_adjustment import resolve_price
from src.data_sources.base import AccessType, SourceDescriptor
from src.database.models.company import Company
from src.database.models.market import MarketPriceClean, MarketPriceRaw
from src.database.models.mixins import QualityStatus
from src.database.models.ops import DataSourceRegistry

OUTLIER_RETURN_THRESHOLD = 0.35  # 35% day-over-day close change -- a conservative heuristic, not a precise ARA/ARB model

_INTERNAL_SOURCE = SourceDescriptor(
    name="internal_price_preprocessing",
    url="internal://preprocessing/market_prices_clean",
    access_type=AccessType.INTERNAL_DERIVED,
)


@dataclasses.dataclass
class PreprocessOutcome:
    ticker: str
    rows_processed: int = 0
    rows_written: int = 0
    outliers_flagged: int = 0
    skipped_reason: str | None = None


def _get_or_create_internal_source(session: Session) -> DataSourceRegistry:
    source = session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == _INTERNAL_SOURCE.name))
    if source is not None:
        return source
    source = DataSourceRegistry(
        name=_INTERNAL_SOURCE.name,
        category="market",
        access_type=_INTERNAL_SOURCE.access_type.value,
        base_url=_INTERNAL_SOURCE.url,
        is_active=True,
    )
    session.add(source)
    session.flush()
    return source


def build_clean_prices(session: Session, ticker: str, price_policy: str) -> PreprocessOutcome:
    outcome = PreprocessOutcome(ticker=ticker)

    company = session.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        outcome.skipped_reason = "no matching Company row"
        return outcome

    raw_rows = list(
        session.scalars(
            select(MarketPriceRaw)
            .where(MarketPriceRaw.company_id == company.id)
            .order_by(MarketPriceRaw.trade_date)
        )
    )
    if not raw_rows:
        outcome.skipped_reason = "no raw price data -- run market backfill/update first"
        return outcome

    source = _get_or_create_internal_source(session)
    now = dt.datetime.now(dt.UTC)

    rows = []
    prev_close: float | None = None
    for raw in raw_rows:
        raw_close = float(raw.close) if raw.close is not None else None
        provider_adjusted = float(raw.adjusted_close_provider) if raw.adjusted_close_provider is not None else None

        adjusted_close, _adj_source = resolve_price(raw_close, provider_adjusted, None, price_policy)
        adjustment_factor = (
            adjusted_close / raw_close if adjusted_close is not None and raw_close not in (None, 0) else None
        )

        is_outlier = False
        if prev_close is not None and raw_close is not None and prev_close != 0:
            pct_change = abs(raw_close - prev_close) / prev_close
            is_outlier = pct_change > OUTLIER_RETURN_THRESHOLD
        if raw_close is not None:
            prev_close = raw_close

        rows.append(
            {
                "company_id": company.id,
                "trade_date": raw.trade_date,
                "open": raw.open,
                "high": raw.high,
                "low": raw.low,
                "close": raw.close,
                "adjusted_close": adjusted_close,
                "volume": raw.volume,
                "market_cap": None,  # needs shares_outstanding, not available (see docs/data_sources.md)
                "adjustment_factor": adjustment_factor,
                "is_outlier_flagged": is_outlier,
                "is_missing_trading_day_filled": False,
                "source_id": source.id,
                "retrieved_at": now,
                "available_at": raw.available_at,
                "period_start": raw.trade_date,
                "period_end": raw.trade_date,
                "currency": "IDR",
                "unit": "unit",
                "is_restated": False,
                "quality_status": QualityStatus.VALID,
            }
        )
        if is_outlier:
            outcome.outliers_flagged += 1

    outcome.rows_processed = len(rows)

    update_col_names = (
        "open",
        "high",
        "low",
        "close",
        "adjusted_close",
        "volume",
        "adjustment_factor",
        "is_outlier_flagged",
        "retrieved_at",
        "available_at",
        "quality_status",
    )
    chunk_size = 1000  # same Postgres bound-parameter reasoning as ingest_ohlcv
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        stmt = insert(MarketPriceClean).values(chunk)
        update_cols = {col: getattr(stmt.excluded, col) for col in update_col_names}
        stmt = stmt.on_conflict_do_update(constraint="uq_price_clean_company_date", set_=update_cols)
        session.execute(stmt)

    outcome.rows_written = len(rows)
    return outcome
