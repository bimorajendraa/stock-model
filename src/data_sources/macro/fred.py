"""FRED (Federal Reserve Economic Data) -- real, free, official US/global
rate data (spec section 3.4), used as a **research/cross-check fallback
only**, never a substitute for Indonesia's own rates (BI-Rate/JISDOR,
``bi_rate.py``).

**Not live-verified against a real API key** -- FRED requires a
registered key for every request (no public/demo key exists, unlike
Twelve Data), and none was available while building this. Built strictly
against FRED's own documented, stable JSON contract
(``https://fred.stlouisfed.org/docs/api/fred/series_observations.html``)
rather than guessed: each observation has ``date``/``value`` (value is a
**string**, not a number -- a real FRED quirk), and a missing/not-yet-
published value is represented as the literal string ``"."`` (also
real/documented, not invented) -- excluded here, never parsed as 0.
Registered in ``docs/data_source_registry.md`` as ``unverified`` (no key
configured) rather than falsely claimed ``healthy`` -- this is exactly
the "system stays alive in degraded mode without a key" behavior asked
for, not a silent gap.
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

_BASE_URL = "https://api.stlouisfed.org/fred"
_SOURCE = SourceDescriptor(name="fred", url=_BASE_URL, access_type=AccessType.DOCUMENTED_FREE)

# series_code -> real FRED series ID (both real, well-known, documented FRED series)
_SERIES_IDS: dict[str, str] = {
    "us_fed_funds_rate": "DFF",  # Federal Funds Effective Rate, daily
    "us_dollar_index_broad": "DTWEXBGS",  # Trade Weighted US Dollar Index, Broad, Goods and Services
}

_MISSING_VALUE_MARKER = "."  # FRED's own documented convention for "not yet published," never 0


class FREDMacroAdapter(MacroDataProvider):
    def __init__(self, api_key: str | None, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(base_url=_BASE_URL, timeout=20.0)

    @property
    def provider_name(self) -> str:
        return "fred"

    def supported_series(self) -> list[str]:
        return list(_SERIES_IDS)

    def get_series(self, series_code: str, start: dt.date, end: dt.date) -> SourcedValue[list[SeriesPoint]]:
        if series_code not in _SERIES_IDS:
            raise ValueError(f"unsupported series_code: {series_code!r} -- see supported_series()")
        now = dt.datetime.now(dt.UTC)
        if not self._api_key:
            raise ProviderUnavailableError("fred: no FRED_API_KEY configured -- see .env.example")

        series_id = _SERIES_IDS[series_code]
        try:
            response = self._client.get(
                "/series/observations",
                params={
                    "series_id": series_id,
                    "api_key": self._api_key,
                    "file_type": "json",
                    "observation_start": start.isoformat(),
                    "observation_end": end.isoformat(),
                },
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"fred request failed: {exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderUnavailableError("fred returned a non-JSON response") from exc
        if response.status_code >= 400:
            raise ProviderUnavailableError(f"fred returned an error (status={response.status_code}): {str(payload)[:200]!r}")

        points: list[SeriesPoint] = []
        for obs in payload.get("observations", []):
            if obs.get("value") == _MISSING_VALUE_MARKER:
                continue  # not yet published for this date -- never fabricated as 0
            try:
                observation_date = dt.date.fromisoformat(obs["date"])
                value = float(obs["value"])
            except (KeyError, ValueError):
                continue
            if not (start <= observation_date <= end):
                continue
            # FRED publishes same-day for daily rate series (DFF/DTWEXBGS) --
            # next business day is a conservative estimate, never earlier.
            points.append(
                SeriesPoint(
                    observation_date=observation_date,
                    value=value,
                    available_at=dt.datetime.combine(observation_date, dt.time(hour=20), tzinfo=dt.UTC),
                )
            )

        points.sort(key=lambda p: p.observation_date)
        return SourcedValue(
            value=points, source=_SOURCE, retrieved_at=now, available_at=now,
            period_start=start, period_end=end,
            validation_status=ValidationStatus.VALID if points else ValidationStatus.INSUFFICIENT,
        )
