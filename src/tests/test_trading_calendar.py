"""Unit tests for trading_calendar -- pure functions, no I/O."""
from __future__ import annotations

import datetime as dt

from src.common.trading_calendar import (
    IDX_TZ,
    freshness_status,
    is_market_session_open,
    is_weekend,
    latest_expected_trading_day,
    previous_trading_day,
    trading_days_between,
)


def test_is_weekend():
    assert is_weekend(dt.date(2026, 7, 25))  # Saturday
    assert is_weekend(dt.date(2026, 7, 26))  # Sunday
    assert not is_weekend(dt.date(2026, 7, 24))  # Friday


def test_previous_trading_day_skips_weekend():
    monday = dt.date(2026, 7, 27)
    assert previous_trading_day(monday) == dt.date(2026, 7, 24)  # Friday


def test_latest_expected_trading_day_before_eod_hour_is_yesterday():
    # Friday 10:00 WIB -> today's EOD not published yet -> expect Thursday
    moment = dt.datetime(2026, 7, 24, 10, 0, tzinfo=IDX_TZ)
    assert latest_expected_trading_day(moment) == dt.date(2026, 7, 23)


def test_latest_expected_trading_day_after_eod_hour_is_today():
    moment = dt.datetime(2026, 7, 24, 20, 0, tzinfo=IDX_TZ)
    assert latest_expected_trading_day(moment) == dt.date(2026, 7, 24)


def test_latest_expected_trading_day_on_weekend_is_last_friday():
    saturday = dt.datetime(2026, 7, 25, 12, 0, tzinfo=IDX_TZ)
    assert latest_expected_trading_day(saturday) == dt.date(2026, 7, 24)


def test_trading_days_between_skips_weekends():
    # Friday to following Monday = 1 trading day (just Monday)
    assert trading_days_between(dt.date(2026, 7, 24), dt.date(2026, 7, 27)) == 1


def test_freshness_fresh_when_up_to_date():
    moment = dt.datetime(2026, 7, 24, 20, 0, tzinfo=IDX_TZ)
    assert freshness_status(dt.date(2026, 7, 24), moment) == "fresh"


def test_freshness_awaiting_eod_when_one_day_behind():
    moment = dt.datetime(2026, 7, 24, 20, 0, tzinfo=IDX_TZ)
    assert freshness_status(dt.date(2026, 7, 23), moment) == "awaiting_eod"


def test_freshness_stale_when_far_behind():
    moment = dt.datetime(2026, 7, 24, 20, 0, tzinfo=IDX_TZ)
    assert freshness_status(dt.date(2026, 7, 1), moment) == "stale"


def test_freshness_stale_when_no_data():
    assert freshness_status(None) == "stale"


def test_is_market_session_open_weekday_daytime():
    moment = dt.datetime(2026, 7, 24, 11, 0, tzinfo=IDX_TZ)
    assert is_market_session_open(moment)


def test_is_market_session_open_false_on_weekend():
    moment = dt.datetime(2026, 7, 25, 11, 0, tzinfo=IDX_TZ)
    assert not is_market_session_open(moment)
