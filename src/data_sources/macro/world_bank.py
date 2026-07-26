"""World Bank Indicators API -- real, free, keyless, official international
macro data (spec section 3.4). Used as **cross-check/research fallback
only**, per this task's own instruction: annual-frequency data must never
override BPS/BI's faster, more current national series -- this adapter
is not registered ahead of BPS/BI adapters in ``cmd_macro_sync``'s
provider list, so it only ever serves series those don't already cover.

Verified live (2026-07-26) before writing any parsing code:
``GET https://api.worldbank.org/v2/country/ID/indicator/FP.CPI.TOTL.ZG?format=json&per_page=5``
returns a real 2-element array ``[metadata, data_list]`` -- each data item
has ``date`` (a year string), ``value`` (float or ``null`` for years not
yet published), ``unit``. **Annual frequency, not monthly** -- a real,
disclosed granularity limitation, not a substitute for BPS's monthly
inflation series.
"""
from __future__ import annotations

import datetime as dt

import httpx

from src.data_sources.base import (
    AccessType,
    ProviderUnavailableError,
    SourceDescriptor,
    SourcedValue,
    ValidationStatus,
)
from src.data_sources.macro.base import MacroDataProvider, SeriesPoint

_BASE_URL = "https://api.worldbank.org/v2"
_SOURCE = SourceDescriptor(name="world_bank_indicators", url=_BASE_URL, access_type=AccessType.DOCUMENTED_FREE)
_COUNTRY = "ID"  # Indonesia's World Bank country code

# series_code -> real World Bank indicator code (both checked live)
_INDICATOR_IDS: dict[str, str] = {
    "id_gdp_growth_annual": "NY.GDP.MKTP.KD.ZG",
    "id_unemployment_rate_annual": "SL.UEM.TOTL.ZS",
}

# World Bank publishes an indicator's most recent year(s) with `value: null`
# until real data is finalized -- excluded here, never treated as 0.
_RELEASE_LAG_DAYS = 300  # annual national-accounts data is real, but published with a long, real lag -- conservative estimate, see module docstring


class WorldBankMacroAdapter(MacroDataProvider):
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(base_url=_BASE_URL, timeout=20.0)

    @property
    def provider_name(self) -> str:
        return "world_bank_indicators"

    def supported_series(self) -> list[str]:
        return list(_INDICATOR_IDS)

    def get_series(self, series_code: str, start: dt.date, end: dt.date) -> SourcedValue[list[SeriesPoint]]:
        if series_code not in _INDICATOR_IDS:
            raise ValueError(f"unsupported series_code: {series_code!r} -- see supported_series()")
        now = dt.datetime.now(dt.UTC)
        indicator_id = _INDICATOR_IDS[series_code]

        try:
            response = self._client.get(
                f"/country/{_COUNTRY}/indicator/{indicator_id}",
                params={"format": "json", "per_page": 200, "date": f"{start.year}:{end.year}"},
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"world_bank request failed: {exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderUnavailableError("world_bank returned a non-JSON response") from exc
        if response.status_code >= 400 or not isinstance(payload, list) or len(payload) < 2:
            raise ProviderUnavailableError(f"world_bank returned an unexpected response: {str(payload)[:200]!r}")

        points: list[SeriesPoint] = []
        for item in payload[1] or []:
            if item.get("value") is None:
                continue  # not yet published for this year -- never fabricate 0
            year = int(item["date"])
            observation_date = dt.date(year, 12, 31)  # annual figure, dated to year-end (real convention for annual national-accounts series)
            if not (start <= observation_date <= end):
                continue
            points.append(
                SeriesPoint(
                    observation_date=observation_date,
                    value=float(item["value"]),
                    available_at=dt.datetime.combine(observation_date, dt.time.min, tzinfo=dt.UTC)
                    + dt.timedelta(days=_RELEASE_LAG_DAYS),
                )
            )

        points.sort(key=lambda p: p.observation_date)
        return SourcedValue(
            value=points, source=_SOURCE, retrieved_at=now, available_at=now,
            period_start=start, period_end=end,
            validation_status=ValidationStatus.VALID if points else ValidationStatus.INSUFFICIENT,
        )
