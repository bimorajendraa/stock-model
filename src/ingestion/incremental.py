"""Backfill vs. incremental-update date windows (spec section 11).

Never re-downloads full history on every run -- a daily update only asks
for a small overlap window past the last stored bar, so a provider revising
a recent bar (common right after close) still gets picked up without
re-pulling years of data.
"""
from __future__ import annotations

import datetime as dt

from src.common.trading_calendar import latest_expected_trading_day

MAX_BACKFILL_YEARS = 10
DEFAULT_UPDATE_OVERLAP_DAYS = 5


def backfill_window(
    listing_date: dt.date | None,
    moment: dt.datetime | None = None,
) -> tuple[dt.date, dt.date]:
    """start = max(10 years ago, IPO/listing date); end = latest completed
    trading day. If ``listing_date`` is unknown, falls back to 10 years --
    never guesses an IPO date."""
    end = latest_expected_trading_day(moment)
    ten_years_ago = end.replace(year=end.year - MAX_BACKFILL_YEARS)
    start = ten_years_ago if listing_date is None else max(ten_years_ago, listing_date)
    return start, end


def update_window(
    last_stored_date: dt.date | None,
    listing_date: dt.date | None = None,
    moment: dt.datetime | None = None,
    overlap_days: int = DEFAULT_UPDATE_OVERLAP_DAYS,
) -> tuple[dt.date, dt.date]:
    """start = last stored trading date - overlap window; end = latest
    completed trading day. No prior data at all -> defers to a full
    backfill window instead of guessing a start date."""
    end = latest_expected_trading_day(moment)
    if last_stored_date is None:
        return backfill_window(listing_date, moment)
    start = last_stored_date - dt.timedelta(days=overlap_days)
    return start, end
