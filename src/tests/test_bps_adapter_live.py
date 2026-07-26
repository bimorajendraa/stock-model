"""Live-network tests for the BPS adapter -- hits the real BPS Web API
using the real BPS_API_KEY from settings (no mock), consistent with how
every other external call in this project is verified. No database
needed, but marked ``integration`` (excluded from the default fast run)
because a live network call shouldn't run on every ``pytest -v``.
"""
from __future__ import annotations

import datetime as dt

import pytest

from src.config.settings import get_settings
from src.data_sources.base import ValidationStatus
from src.data_sources.macro.bps import BPSMacroAdapter

pytestmark = pytest.mark.integration


@pytest.fixture()
def adapter():
    settings = get_settings()
    if not settings.bps_api_key:
        pytest.skip("BPS_API_KEY not configured in this environment")
    return BPSMacroAdapter(api_key=settings.bps_api_key)


def test_get_series_returns_real_recent_inflation_data(adapter):
    end = dt.date(2026, 7, 25)
    result = adapter.get_series("id_inflation_mom", dt.date(2024, 1, 1), end)
    assert result.validation_status == ValidationStatus.VALID
    assert result.value  # real points, not empty
    assert all(dt.date(2024, 1, 1) <= p.observation_date <= end for p in result.value)


def test_get_series_spans_multiple_3_year_chunks(adapter):
    # BPS caps 'th' at 3 years per request -- this range needs 4+ chunked
    # calls; a chunking bug would silently drop years, not error.
    result = adapter.get_series("id_inflation_mom", dt.date(2016, 1, 1), dt.date(2026, 7, 25))
    assert result.validation_status == ValidationStatus.VALID
    years_covered = {p.observation_date.year for p in result.value}
    for year in (2016, 2018, 2020, 2022, 2024, 2026):
        assert year in years_covered, f"year {year} missing -- possible chunking bug"


def test_available_at_is_set_per_point_not_batch_now(adapter):
    result = adapter.get_series("id_inflation_mom", dt.date(2016, 1, 1), dt.date(2026, 7, 25))
    now = dt.datetime.now(dt.UTC)
    # an old (e.g. 2016) observation's available_at must reflect its own
    # real-world publication lag, not today -- otherwise a point-in-time
    # consumer would wrongly think 2016 inflation only became known now.
    old_point = next(p for p in result.value if p.observation_date.year == 2016)
    assert old_point.available_at is not None
    assert old_point.available_at < now - dt.timedelta(days=365 * 5)


def test_inflation_values_are_plausible_percentages():
    settings = get_settings()
    if not settings.bps_api_key:
        pytest.skip("BPS_API_KEY not configured in this environment")
    adapter = BPSMacroAdapter(api_key=settings.bps_api_key)
    result = adapter.get_series("id_inflation_mom", dt.date(2024, 1, 1), dt.date(2026, 7, 25))
    # monthly inflation is a small percentage, not an index level in the
    # hundreds -- catches a unit/series mixup, not just "a number came back"
    assert all(-5.0 < p.value < 5.0 for p in result.value)


def test_unsupported_series_code_raises(adapter):
    with pytest.raises(ValueError):
        adapter.get_series("id_cpi_level", dt.date(2020, 1, 1), dt.date(2020, 12, 31))
