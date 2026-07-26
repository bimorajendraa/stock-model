"""Unit tests for pure BPS adapter logic -- no network, no DB."""
from __future__ import annotations

import datetime as dt

from src.data_sources.macro.bps import BPSMacroAdapter, _last_day_of_month, _th_val


def test_th_val_matches_real_bps_th_ids():
    # Confirmed live against BPS's own /list/model/th endpoint on
    # 2026-07-25: th_id=126 <-> "2026", th_id=117 <-> "2017", etc.
    assert _th_val(2026) == 126
    assert _th_val(2017) == 117
    assert _th_val(2020) == 120


def test_last_day_of_month_handles_leap_year():
    assert _last_day_of_month(2024, 2) == dt.date(2024, 2, 29)
    assert _last_day_of_month(2025, 2) == dt.date(2025, 2, 28)


def test_last_day_of_month_hand_computed():
    assert _last_day_of_month(2026, 1) == dt.date(2026, 1, 31)
    assert _last_day_of_month(2026, 4) == dt.date(2026, 4, 30)
    assert _last_day_of_month(2026, 12) == dt.date(2026, 12, 31)


def test_available_at_for_is_strictly_after_month_end():
    adapter = BPSMacroAdapter(api_key=None)
    observation_date = dt.date(2026, 4, 30)
    available_at = adapter.available_at_for(observation_date)
    assert available_at.date() > observation_date


def test_available_at_for_crosses_year_boundary():
    adapter = BPSMacroAdapter(api_key=None)
    available_at = adapter.available_at_for(dt.date(2025, 12, 31))
    assert available_at.date() == dt.date(2026, 1, 11)  # Jan 1 2026 + 10 days
