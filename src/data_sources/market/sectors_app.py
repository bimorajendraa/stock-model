"""Sectors.app adapter (spec §3.2).

Implemented against the live OpenAPI schema fetched directly from
``https://api.sectors.app/schema/`` on 2026-07-24 (not from memory or a
docs page -- ``docs.sectors.app`` blocks automated fetches with a 403, but
the API's own machine-readable schema does not). No API key was available
to empirically test real responses; the request/response shapes below
match the schema's documented examples exactly. Re-verify against
``/schema/`` if Sectors.app ships a breaking change.

Known limitation, not a bug: ``GET /v2/daily/{symbol}/`` returns only
close price, volume, and market cap -- no open/high/low. ``get_ohlcv``
returns bars with ``open``/``high``/``low`` set to ``None`` rather than
fabricating them. Max 90-day window per request; longer ranges are
paginated by this adapter across multiple requests.

No free tier as of this writing (https://sectors.app/pricing) -- this
adapter is inert (raises ``ProviderUnavailableError`` on first use) until
``SECTORS_APP_API_KEY`` is configured.
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
from src.data_sources.market.base import MarketDataProvider, OHLCVBar

_BASE_URL = "https://api.sectors.app"
_SOURCE = SourceDescriptor(name="sectors_app", url=_BASE_URL, access_type=AccessType.FALLBACK_PROVIDER)
_MAX_WINDOW_DAYS = 90
_MAX_PAGE_SIZE = 200


class SectorsAppMarketProvider(MarketDataProvider):
    def __init__(self, api_key: str | None, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(base_url=_BASE_URL, timeout=15.0)

    @property
    def provider_name(self) -> str:
        return "sectors_app"

    def _get(self, path: str, params: dict) -> dict | list:
        if not self._api_key:
            raise ProviderUnavailableError("sectors_app: SECTORS_APP_API_KEY not configured")
        try:
            response = self._client.get(path, params=params, headers={"Authorization": self._api_key})
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"sectors_app request failed: {exc}") from exc

        if response.status_code == 429:
            raise ProviderUnavailableError("sectors_app rate limit exceeded")
        if response.status_code >= 400:
            raise ProviderUnavailableError(f"sectors_app error {response.status_code}: {response.text[:200]}")
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderUnavailableError("sectors_app returned a non-JSON response") from exc

    def list_active_tickers(self) -> SourcedValue[list[str]]:
        now = dt.datetime.now(dt.UTC)
        tickers: list[str] = []
        offset = 0
        while True:
            payload = self._get("/v2/companies/", {"limit": _MAX_PAGE_SIZE, "offset": offset})
            results = payload.get("results", []) if isinstance(payload, dict) else []
            tickers.extend(row["symbol"].removesuffix(".JK") for row in results if row.get("symbol"))
            pagination = payload.get("pagination", {}) if isinstance(payload, dict) else {}
            if not pagination.get("has_next"):
                break
            offset = pagination.get("next_offset", offset + _MAX_PAGE_SIZE)

        return SourcedValue(
            value=tickers,
            source=_SOURCE,
            retrieved_at=now,
            available_at=now,
            period_start=None,
            period_end=None,
            validation_status=ValidationStatus.VALID if tickers else ValidationStatus.INSUFFICIENT,
        )

    def get_ohlcv(self, ticker: str, start: dt.date, end: dt.date) -> SourcedValue[list[OHLCVBar]]:
        now = dt.datetime.now(dt.UTC)
        bars: list[OHLCVBar] = []
        window_start = start
        while window_start <= end:
            window_end = min(window_start + dt.timedelta(days=_MAX_WINDOW_DAYS - 1), end)
            payload = self._get(
                f"/v2/daily/{ticker}/",
                {"start": window_start.isoformat(), "end": window_end.isoformat()},
            )
            rows = payload if isinstance(payload, list) else []
            bars.extend(
                OHLCVBar(
                    trade_date=dt.date.fromisoformat(row["date"]),
                    open=None,
                    high=None,
                    low=None,
                    close=row.get("close"),
                    volume=row.get("volume"),
                )
                for row in rows
            )
            window_start = window_end + dt.timedelta(days=1)

        bars.sort(key=lambda b: b.trade_date)
        return SourcedValue(
            value=bars,
            source=_SOURCE,
            retrieved_at=now,
            available_at=now,
            period_start=start,
            period_end=end,
            validation_status=ValidationStatus.VALID if bars else ValidationStatus.INSUFFICIENT,
        )

    def get_corporate_actions(self, ticker: str, start: dt.date, end: dt.date) -> SourcedValue[list[dict]]:
        now = dt.datetime.now(dt.UTC)
        payload = self._get(f"/v2/company/corporate-actions/{ticker}/", {})
        # Response is {symbol, corporate_actions: {stock_split: [...], dividend:
        # [...], bonus, warrant, right_issue, agm, upcoming_dividend}} -- no
        # date-range filter on the endpoint itself, so this adapter fetches
        # full history and filters to [start, end] client-side, using each
        # action type's own date field (verified against the live schema's
        # examples, not guessed).
        grouped = payload.get("corporate_actions", {}) if isinstance(payload, dict) else {}
        date_fields = {
            "stock_split": "date",
            "dividend": "ex_date",
            "right_issue": "ex_date",
            "bonus": "ex_date",
        }
        actions: list[dict] = []
        for action_type, date_field in date_fields.items():
            for entry in grouped.get(action_type) or []:
                entry_date = entry.get(date_field)
                if entry_date and start.isoformat() <= entry_date <= end.isoformat():
                    actions.append({"action_type": action_type, **entry})

        return SourcedValue(
            value=actions,
            source=_SOURCE,
            retrieved_at=now,
            available_at=now,
            period_start=start,
            period_end=end,
            validation_status=ValidationStatus.VALID,
        )
