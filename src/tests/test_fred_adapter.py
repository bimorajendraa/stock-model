"""Unit tests for the FRED macro adapter. Response shape matches FRED's
own documented JSON contract (not live-verified against a real key --
see the adapter's module docstring for why)."""
from __future__ import annotations

import datetime as dt

import httpx
import respx

from src.data_sources.base import ProviderUnavailableError, ValidationStatus
from src.data_sources.macro.fred import FREDMacroAdapter

_DOCUMENTED_SHAPE_RESPONSE = {
    "realtime_start": "2026-07-01",
    "realtime_end": "2026-07-26",
    "observation_start": "2026-07-01",
    "observation_end": "2026-07-26",
    "units": "lin",
    "output_type": 1,
    "file_type": "json",
    "order_by": "observation_date",
    "sort_order": "asc",
    "count": 3,
    "offset": 0,
    "limit": 100000,
    "observations": [
        {"realtime_start": "2026-07-01", "realtime_end": "2026-07-26", "date": "2026-07-01", "value": "5.33"},
        {"realtime_start": "2026-07-01", "realtime_end": "2026-07-26", "date": "2026-07-02", "value": "5.33"},
        {"realtime_start": "2026-07-01", "realtime_end": "2026-07-26", "date": "2026-07-03", "value": "."},
    ],
}


def test_no_api_key_raises_provider_unavailable_not_a_crash():
    adapter = FREDMacroAdapter(api_key=None)
    try:
        adapter.get_series("us_fed_funds_rate", dt.date(2026, 1, 1), dt.date(2026, 12, 31))
        raise AssertionError("expected ProviderUnavailableError")
    except ProviderUnavailableError as exc:
        assert "FRED_API_KEY" in str(exc)


@respx.mock
def test_get_series_parses_documented_response_shape_and_excludes_missing_marker():
    respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(200, json=_DOCUMENTED_SHAPE_RESPONSE)
    )
    adapter = FREDMacroAdapter(api_key="test-key")
    result = adapter.get_series("us_fed_funds_rate", dt.date(2026, 1, 1), dt.date(2026, 12, 31))

    assert result.validation_status == ValidationStatus.VALID
    assert [p.observation_date for p in result.value] == [dt.date(2026, 7, 1), dt.date(2026, 7, 2)]
    assert [p.value for p in result.value] == [5.33, 5.33]
    # the "." (not-yet-published) observation on 2026-07-03 is never included


def test_unsupported_series_code_raises():
    adapter = FREDMacroAdapter(api_key="test-key")
    try:
        adapter.get_series("not_a_real_series", dt.date(2016, 1, 1), dt.date(2026, 12, 31))
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
