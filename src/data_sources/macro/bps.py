"""BPS (Statistik Indonesia) Web API adapter -- real Indonesia-specific
macro series (spec section 3.4): national inflation, month-over-month.
Fills the gap `yahoo_finance.py` in this same package explicitly could
not (BI-Rate/BPS inflation were a documented "needs a credential we
don't have" gap until a real, free, user-provided API key made this
possible).

**Verified live (2026-07-25)** with the real key, not guessed from docs:
- ``GET /list/model/subject/domain/0000/...`` -> subject catalog;
  "Inflasi" is ``sub_id=3``.
- ``GET /list/model/var/domain/0000/subject/3/...`` -> ``var_id=1`` is
  "Inflasi Bulanan (M-to-M)" (%), a live, continuously updated series
  (78 real monthly points fetched for 2020-2026, most recent June 2026).
  ``var_id=2`` ("Indeks Harga Konsumen (Umum)", the CPI index level) was
  also checked but is a **discontinued series** -- its own ``th`` list
  tops out at 2019, years before this project's 2016-2026 window even
  needs current data (BPS appears to have superseded it with a
  differently-based series after a rebasing, per the variable's own
  methodology notes; the successor wasn't identified and is not guessed
  at here). Deliberately not included in ``SERIES_CATALOG`` -- better to
  cover one series well than include a second that silently stops
  updating.
- ``GET /list/model/data/domain/0000/var/{var_id}/th/{th_start}:{th_end}/key/...``
  -> real data. The response's ``vervar`` list (labeled "Kota Inflasi" --
  a per-city breakdown table) includes ``val=9999, label="INDONESIA"``:
  the national aggregate row living inside that same table, not a
  separate endpoint. **The ``th`` range is capped at 3 years per request**
  (found live: "The maximum allowed number of years for the 'th'
  parameter is 3") -- this adapter chunks automatically.
- ``datacontent`` keys are ``{vervar}{var_id}{turvar}{th_val}{turtahun_val}``
  concatenated with no separator -- decoded by cross-referencing the same
  response's own ``tahun``/``turtahun`` label lists, not guessed.
  ``turvar`` is always ``"0"`` ("Tidak ada") for this variable.
  ``th_val = calendar_year - 1900`` (confirmed against the real ``th``
  list for 2017-2026 -- every value matched exactly). ``turtahun_val``
  1-12 = month, 13 = "Tahunan" (an annual aggregate row, not a monthly
  point) -- excluded here; this adapter only returns real monthly
  observations, never fabricates one for the annual row.

**Known limitation, stated plainly**: BPS's API doesn't expose a real
per-observation publication/release date. ``available_at`` here is a
**conservative estimate**: end-of-month + 10 days -- BPS's real practice
is to publish monthly inflation on the 1st-2nd working day of the
following month, so this errs toward *later* than the real release,
never earlier (same safe-direction discipline as
``docs/fundamentals.md``'s `available_at` estimate for financial
statements -- underestimating is the actual leakage risk).
"""
from __future__ import annotations

import calendar
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
from src.data_sources.macro.taxonomy import SERIES_CATALOG

_BASE_URL = "https://webapi.bps.go.id/v1/api"
_SOURCE = SourceDescriptor(name="bps", url=_BASE_URL, access_type=AccessType.DOCUMENTED_FREE)

_NATIONAL_VERVAR = 9999  # "INDONESIA" row inside the "Kota Inflasi" per-city table
_TURVAR_NONE = 0  # "Tidak ada" -- no sub-breakdown for these two variables
_ANNUAL_TURTAHUN = 13  # "Tahunan" -- an annual aggregate row, not a monthly observation
_RELEASE_LAG_DAYS = 10  # conservative estimate past BPS's real ~1-2 day publication lag

# series_code -> BPS var_id (var_id=2, "Indeks Harga Konsumen (Umum)",
# deliberately excluded -- discontinued, see module docstring)
_VAR_IDS: dict[str, int] = {
    "id_inflation_mom": 1,
}
assert _VAR_IDS.keys() <= SERIES_CATALOG.keys()  # subset -- SERIES_CATALOG also has Yahoo-served series


def _th_val(year: int) -> int:
    return year - 1900


def _last_day_of_month(year: int, month: int) -> dt.date:
    return dt.date(year, month, calendar.monthrange(year, month)[1])


class BPSMacroAdapter(MacroDataProvider):
    def __init__(self, api_key: str | None, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(base_url=_BASE_URL, timeout=20.0)

    @property
    def provider_name(self) -> str:
        return "bps"

    def supported_series(self) -> list[str]:
        return list(_VAR_IDS)

    def _get(self, path: str) -> dict:
        try:
            response = self._client.get(path)
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"bps request failed: {exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderUnavailableError("bps returned a non-JSON response") from exc
        if response.status_code >= 400 or payload.get("status") not in ("OK", None):
            raise ProviderUnavailableError(f"bps returned an error: {payload}")
        return payload

    def get_series(self, series_code: str, start: dt.date, end: dt.date) -> SourcedValue[list[SeriesPoint]]:
        now = dt.datetime.now(dt.UTC)
        if series_code not in _VAR_IDS:
            raise ValueError(f"unsupported series_code: {series_code!r} -- see supported_series()")
        if not self._api_key:
            raise ProviderUnavailableError("bps: no BPS_API_KEY configured")

        var_id = _VAR_IDS[series_code]
        points: list[SeriesPoint] = []
        # BPS caps the 'th' range parameter at 3 years per request (found
        # live: "The maximum allowed number of years for the 'th'
        # parameter is 3") -- chunk the requested range into <=3-year
        # windows rather than guessing a smaller-but-still-wrong limit.
        for chunk_start_year in range(start.year, end.year + 1, 3):
            chunk_end_year = min(chunk_start_year + 2, end.year)
            th_start, th_end = _th_val(chunk_start_year), _th_val(chunk_end_year)
            payload = self._get(
                f"/list/model/data/domain/0000/var/{var_id}/th/{th_start}:{th_end}/key/{self._api_key}"
            )
            if payload.get("data-availability") != "available":
                continue

            year_by_th_val = {t["val"]: int(t["label"]) for t in payload.get("tahun", [])}
            month_by_turtahun = {
                t["val"]: t["val"] for t in payload.get("turtahun", []) if t["val"] != _ANNUAL_TURTAHUN
            }
            prefix = f"{_NATIONAL_VERVAR}{var_id}{_TURVAR_NONE}"

            for key, value in payload.get("datacontent", {}).items():
                if not key.startswith(prefix) or value is None:
                    continue
                suffix = key[len(prefix) :]
                th_val, turtahun_val = int(suffix[:3]), int(suffix[3:])
                if th_val not in year_by_th_val or turtahun_val not in month_by_turtahun:
                    continue
                observation_date = _last_day_of_month(year_by_th_val[th_val], turtahun_val)
                if start <= observation_date <= end:
                    points.append(
                        SeriesPoint(
                            observation_date=observation_date,
                            value=float(value),
                            available_at=self.available_at_for(observation_date),
                        )
                    )

        points.sort(key=lambda p: p.observation_date)
        return SourcedValue(
            value=points,
            source=_SOURCE,
            retrieved_at=now,
            available_at=now,
            period_start=start,
            period_end=end,
            validation_status=ValidationStatus.VALID if points else ValidationStatus.INSUFFICIENT,
        )

    def available_at_for(self, observation_date: dt.date) -> dt.datetime:
        """Conservative estimated publication date for a monthly
        observation -- see module docstring. Exposed separately from
        ``get_series``'s (batch) ``available_at`` because each monthly
        point has its own real release date, unlike a single fetch-time
        timestamp."""
        next_month_first = (observation_date.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        return dt.datetime.combine(
            next_month_first + dt.timedelta(days=_RELEASE_LAG_DAYS), dt.time.min, tzinfo=dt.UTC
        )
