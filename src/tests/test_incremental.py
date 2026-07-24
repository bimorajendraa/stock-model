"""Unit tests for backfill/update window logic."""
from __future__ import annotations

import datetime as dt

from src.common.trading_calendar import IDX_TZ
from src.ingestion.incremental import backfill_window, update_window

MOMENT = dt.datetime(2026, 7, 24, 20, 0, tzinfo=IDX_TZ)  # Friday, after EOD hour


def test_backfill_window_defaults_to_ten_years():
    start, end = backfill_window(listing_date=None, moment=MOMENT)
    assert end == dt.date(2026, 7, 24)
    assert start == dt.date(2016, 7, 24)


def test_backfill_window_respects_recent_listing_date():
    listing = dt.date(2024, 1, 15)
    start, _end = backfill_window(listing_date=listing, moment=MOMENT)
    assert start == listing  # IPO more recent than 10y ago -- use IPO date


def test_backfill_window_ignores_old_listing_date():
    listing = dt.date(1995, 1, 1)  # listed before the 10y window
    start, _end = backfill_window(listing_date=listing, moment=MOMENT)
    assert start == dt.date(2016, 7, 24)  # capped at 10 years, not full history


def test_update_window_uses_overlap():
    last_stored = dt.date(2026, 7, 20)
    start, end = update_window(last_stored, moment=MOMENT, overlap_days=5)
    assert start == dt.date(2026, 7, 15)
    assert end == dt.date(2026, 7, 24)


def test_update_window_with_no_prior_data_falls_back_to_backfill():
    start, _end = update_window(None, listing_date=dt.date(2024, 1, 15), moment=MOMENT)
    assert start == dt.date(2024, 1, 15)
