"""Unit tests for the World Bank Indicators macro adapter. Response shape
is the real one fetched live (2026-07-26) from
``api.worldbank.org/v2/country/ID/indicator/FP.CPI.TOTL.ZG`` before this
adapter was written -- see its module docstring."""
from __future__ import annotations

import datetime as dt

import httpx
import respx

from src.data_sources.base import ProviderUnavailableError, ValidationStatus
from src.data_sources.macro.world_bank import WorldBankMacroAdapter

_REAL_SHAPE_RESPONSE = [
    {"page": 1, "pages": 1, "per_page": 50, "total": 3, "sourceid": "2", "lastupdated": "2026-07-13"},
    [
        {"indicator": {"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth (annual %)"}, "country": {"id": "ID", "value": "Indonesia"}, "countryiso3code": "IDN", "date": "2025", "value": 5.108, "unit": "", "obs_status": "", "decimal": 1},
        {"indicator": {"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth (annual %)"}, "country": {"id": "ID", "value": "Indonesia"}, "countryiso3code": "IDN", "date": "2024", "value": 5.033, "unit": "", "obs_status": "", "decimal": 1},
        {"indicator": {"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth (annual %)"}, "country": {"id": "ID", "value": "Indonesia"}, "countryiso3code": "IDN", "date": "2026", "value": None, "unit": "", "obs_status": "", "decimal": 1},
    ],
]


@respx.mock
def test_get_series_parses_real_response_shape_and_excludes_null_values():
    respx.get("https://api.worldbank.org/v2/country/ID/indicator/NY.GDP.MKTP.KD.ZG").mock(
        return_value=httpx.Response(200, json=_REAL_SHAPE_RESPONSE)
    )
    adapter = WorldBankMacroAdapter()
    result = adapter.get_series("id_gdp_growth_annual", dt.date(2016, 1, 1), dt.date(2026, 12, 31))

    assert result.validation_status == ValidationStatus.VALID
    assert [p.observation_date for p in result.value] == [dt.date(2024, 12, 31), dt.date(2025, 12, 31)]
    assert [p.value for p in result.value] == [5.033, 5.108]
    # 2026's null value never becomes a fabricated 0 or gets included


@respx.mock
def test_get_series_raises_on_malformed_response():
    respx.get("https://api.worldbank.org/v2/country/ID/indicator/NY.GDP.MKTP.KD.ZG").mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"})
    )
    adapter = WorldBankMacroAdapter()
    try:
        adapter.get_series("id_gdp_growth_annual", dt.date(2016, 1, 1), dt.date(2026, 12, 31))
        raise AssertionError("expected ProviderUnavailableError")
    except ProviderUnavailableError:
        pass


def test_unsupported_series_code_raises():
    adapter = WorldBankMacroAdapter()
    try:
        adapter.get_series("not_a_real_series", dt.date(2016, 1, 1), dt.date(2026, 12, 31))
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
