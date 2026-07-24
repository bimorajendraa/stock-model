"""IDX trading calendar and data-freshness classification (spec section 12).

Deliberately does NOT model IDX public holidays: no citable, programmatically
accessible official holiday calendar was available while writing this (the
same access problem as idx.co.id generally -- see docs/data_sources.md).
Weekends are the only exclusion modeled. This is a known simplification,
not a silent inaccuracy -- a holiday shows up as a same-shape gap as any
other missing trading day, and the freshness logic below tolerates a
1-3 trading-day gap before calling data "stale" specifically so an
unmodeled holiday doesn't get misreported as a data quality failure.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

IDX_TZ = ZoneInfo("Asia/Jakarta")

# IDX's continuous trading session runs into the afternoon; 16:00 WIB is a
# conservative "session is definitely closed" bound (actual close varies
# slightly by session/day). EOD data is not expected to be published by
# every provider immediately at close, hence the separate publish buffer.
MARKET_OPEN_TIME = dt.time(9, 0)
MARKET_CLOSE_TIME = dt.time(16, 0)
EOD_PUBLISH_HOUR = 19  # providers get until 19:00 WIB before "awaiting_eod" becomes "provider_delayed"


def now_jakarta() -> dt.datetime:
    return dt.datetime.now(IDX_TZ)


def is_weekend(d: dt.date) -> bool:
    return d.weekday() >= 5


def is_market_session_open(moment: dt.datetime | None = None) -> bool:
    moment = moment or now_jakarta()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=IDX_TZ)
    return not is_weekend(moment.date()) and MARKET_OPEN_TIME <= moment.time() <= MARKET_CLOSE_TIME


def previous_trading_day(d: dt.date) -> dt.date:
    """Previous weekday before ``d`` -- see module docstring re: holidays."""
    d -= dt.timedelta(days=1)
    while is_weekend(d):
        d -= dt.timedelta(days=1)
    return d


def latest_expected_trading_day(moment: dt.datetime | None = None) -> dt.date:
    """The most recent trading day whose data *should* exist by ``moment``,
    accounting for the EOD publish buffer -- never claims today's data
    should exist before the market has even closed."""
    moment = moment or now_jakarta()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=IDX_TZ)
    today = moment.date()

    if is_weekend(today):
        return previous_trading_day(today)
    if moment.hour < EOD_PUBLISH_HOUR:
        # Today's EOD data may not be published yet -- expect yesterday's.
        return previous_trading_day(today)
    return today


def trading_days_between(start: dt.date, end: dt.date) -> int:
    """Count of weekdays strictly between start and end (exclusive of
    start, inclusive of end) -- used to size a data gap in trading days
    rather than calendar days (so a Friday-to-Monday gap isn't 3)."""
    if end <= start:
        return 0
    count = 0
    d = start
    while d < end:
        d += dt.timedelta(days=1)
        if not is_weekend(d):
            count += 1
    return count


def freshness_status(latest_bar_date: dt.date | None, moment: dt.datetime | None = None) -> str:
    """fresh | awaiting_eod | provider_delayed | stale -- never asserts
    "stale" just because it's a weekend or an unmodeled holiday gap of a
    day or two."""
    moment = moment or now_jakarta()
    expected = latest_expected_trading_day(moment)

    if latest_bar_date is None:
        return "stale"
    if latest_bar_date >= expected:
        return "fresh"

    gap = trading_days_between(latest_bar_date, expected)
    if gap <= 1:
        return "awaiting_eod"
    if gap <= 3:
        return "provider_delayed"
    return "stale"
