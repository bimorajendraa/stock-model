"""Unit tests for daily scheduler time calculation."""
from __future__ import annotations

import datetime as dt

from src.orchestration.news_scheduler import next_scheduled_run


def test_next_run_is_same_day_before_schedule():
    now = dt.datetime(2026, 7, 27, 20, 0, tzinfo=dt.UTC)  # 03:00 Jakarta
    result = next_scheduled_run(now, "Asia/Jakarta", 6, 0)
    assert result == dt.datetime(2026, 7, 28, 6, 0, tzinfo=result.tzinfo)


def test_next_run_rolls_to_tomorrow_after_schedule():
    now = dt.datetime(2026, 7, 27, 1, 0, tzinfo=dt.UTC)  # 08:00 Jakarta
    result = next_scheduled_run(now, "Asia/Jakarta", 6, 0)
    assert result.date() == dt.date(2026, 7, 28)
    assert (result.hour, result.minute) == (6, 0)
