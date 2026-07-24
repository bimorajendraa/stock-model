"""Market data reconciliation (spec section 9).

The spec asks to reconcile against IDX's own official trading summary.
That isn't practically available to this project -- idx.co.id blocks
automated access outright (see docs/data_sources.md), and no other
citable official IDX price-verification API was found. Rather than fake
an "IDX verification" that doesn't exist, this module does genuine
cross-provider reconciliation (e.g. Yahoo Finance vs. Twelve Data) when a
second independent provider is actually available, and honestly reports
``verification_unavailable`` when it isn't -- never silently skipped,
never claimed as matched.
"""
from __future__ import annotations

import dataclasses
import datetime as dt

from sqlalchemy.orm import Session

from src.database.models.market import MarketDataReconciliation, MarketPriceRaw

DEFAULT_PRICE_TOLERANCE_PCT = 0.5


@dataclasses.dataclass
class ReconciliationComparison:
    status: str  # matched | within_tolerance | mismatch | verification_unavailable
    absolute_difference: float | None
    percentage_difference: float | None
    volume_difference: int | None


def compute_reconciliation(
    primary_close: float | None,
    verification_close: float | None,
    primary_volume: int | None = None,
    verification_volume: int | None = None,
    tolerance_pct: float = DEFAULT_PRICE_TOLERANCE_PCT,
) -> ReconciliationComparison:
    if verification_close is None or primary_close is None:
        return ReconciliationComparison("verification_unavailable", None, None, None)

    abs_diff = abs(primary_close - verification_close)
    pct_diff = (abs_diff / primary_close * 100) if primary_close else None
    vol_diff = (
        abs(primary_volume - verification_volume)
        if primary_volume is not None and verification_volume is not None
        else None
    )

    if abs_diff == 0:
        status = "matched"
    elif pct_diff is not None and pct_diff <= tolerance_pct:
        status = "within_tolerance"
    else:
        status = "mismatch"

    return ReconciliationComparison(status, abs_diff, pct_diff, vol_diff)


def reconcile_and_store(
    session: Session,
    company_id: int,
    trading_date: dt.date,
    primary_provider: str,
    verification_provider: str,
    primary_close: float | None,
    verification_close: float | None,
    primary_volume: int | None = None,
    verification_volume: int | None = None,
    tolerance_pct: float = DEFAULT_PRICE_TOLERANCE_PCT,
) -> MarketDataReconciliation:
    """Writes one row to market_data_reconciliation and, if the primary
    provider's raw row for this date exists, updates its
    verification_status to reflect the outcome -- one ticker/date result
    never proves a provider "verified" globally (spec: "Jangan menyatakan
    provider tervalidasi hanya karena satu ticker cocok"), it just updates
    that one row's own status."""
    comparison = compute_reconciliation(
        primary_close, verification_close, primary_volume, verification_volume, tolerance_pct
    )

    record = MarketDataReconciliation(
        company_id=company_id,
        trading_date=trading_date,
        primary_provider=primary_provider,
        verification_provider=verification_provider,
        primary_close=primary_close,
        verification_close=verification_close,
        absolute_difference=comparison.absolute_difference,
        percentage_difference=comparison.percentage_difference,
        volume_difference=comparison.volume_difference,
        status=comparison.status,
        checked_at=dt.datetime.now(dt.UTC),
    )
    session.add(record)

    if comparison.status in ("matched", "within_tolerance", "mismatch"):
        new_status = "reconciled_mismatch" if comparison.status == "mismatch" else "reconciled_matched"
        primary_row = session.query(MarketPriceRaw).filter(
            MarketPriceRaw.company_id == company_id,
            MarketPriceRaw.trade_date == trading_date,
        )
        for row in primary_row:
            row.verification_status = new_status

    return record
