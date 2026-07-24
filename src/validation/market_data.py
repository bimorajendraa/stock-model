"""OHLCV data-quality validation (spec section 5).

A bar that fails validation is never silently dropped and never written to
``market_prices_raw`` -- it goes to ``market_price_quarantine`` instead,
with the specific errors attached, so nothing disappears without a trace.
"""
from __future__ import annotations

import dataclasses
import datetime as dt

from src.common.trading_calendar import IDX_TZ
from src.data_sources.market.base import OHLCVBar


@dataclasses.dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str]


def validate_ohlcv_bar(bar: OHLCVBar, today: dt.date | None = None) -> ValidationResult:
    """Structural sanity checks only -- never rejects a bar just because a
    field is ``None`` (e.g. today's still-forming bar has no close yet;
    that's a freshness concern, handled by ``trading_calendar``, not a
    validation failure)."""
    today = today or dt.datetime.now(IDX_TZ).date()
    errors: list[str] = []

    for name, value in (("open", bar.open), ("high", bar.high), ("low", bar.low), ("close", bar.close)):
        if value is not None and value <= 0:
            errors.append(f"{name} must be > 0, got {value}")

    if bar.high is not None:
        if bar.open is not None and bar.high < bar.open:
            errors.append(f"high ({bar.high}) < open ({bar.open})")
        if bar.close is not None and bar.high < bar.close:
            errors.append(f"high ({bar.high}) < close ({bar.close})")
        if bar.low is not None and bar.high < bar.low:
            errors.append(f"high ({bar.high}) < low ({bar.low})")

    if bar.low is not None:
        if bar.open is not None and bar.low > bar.open:
            errors.append(f"low ({bar.low}) > open ({bar.open})")
        if bar.close is not None and bar.low > bar.close:
            errors.append(f"low ({bar.low}) > close ({bar.close})")

    if bar.volume is not None and bar.volume < 0:
        errors.append(f"volume must be >= 0, got {bar.volume}")

    if bar.trade_date > today:
        errors.append(f"trade_date {bar.trade_date} is in the future (today={today})")

    return ValidationResult(is_valid=not errors, errors=errors)
