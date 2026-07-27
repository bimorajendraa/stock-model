"""Twelve Data adapter (spec §3.2).

Verified live against the real API on 2026-07-24 (not written from memory):
- ``GET /stocks?exchange=IDX&apikey=...`` returns real IDX tickers/names
  even with the public ``demo`` key.
- ``GET /time_series`` requires a real (still free-to-register) key; the
  API's own error message confirms the key is free ("absolutely free, and
  it's yours for a lifetime").
- Docs: https://twelvedata.com/docs

Corporate actions (splits/dividends) are intentionally NOT implemented here
-- Twelve Data's endpoints for those were not verified against a live
response before this file was written, and the spec forbids guessing API
contracts. Implement ``get_corporate_actions`` only after confirming the
real endpoint shape.
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
from src.data_sources.market.base import CompanyRecord, MarketDataProvider, OHLCVBar
from src.data_sources.market.capability import classify_twelve_data_error, is_twelve_data_error_payload

_BASE_URL = "https://api.twelvedata.com"
_SOURCE = SourceDescriptor(name="twelve_data", url=_BASE_URL, access_type=AccessType.DOCUMENTED_FREE)


class TwelveDataMarketProvider(MarketDataProvider):
    def __init__(self, api_key: str | None, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(base_url=_BASE_URL, timeout=15.0)

    @property
    def provider_name(self) -> str:
        return "twelve_data"

    def _get(self, path: str, params: dict) -> dict:
        if self._api_key:
            params = {**params, "apikey": self._api_key}
        try:
            response = self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"twelve_data request failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderUnavailableError("twelve_data returned a non-JSON response") from exc

        # See capability.is_twelve_data_error_payload's docstring: an
        # earlier version of this method only checked "status" == "error"
        # and missed the demo-key case entirely (no "status" key on that
        # response at all), which a live capability probe caught.
        if response.status_code >= 400 or is_twelve_data_error_payload(payload if isinstance(payload, dict) else {}):
            raise classify_twelve_data_error(response.status_code, payload if isinstance(payload, dict) else {})
        return payload

    def list_active_tickers(self) -> SourcedValue[list[str]]:
        now = dt.datetime.now(dt.UTC)
        payload = self._get("/stocks", {"exchange": "IDX"})
        rows = payload.get("data", [])
        tickers = [row["symbol"] for row in rows if row.get("symbol")]
        return SourcedValue(
            value=tickers,
            source=_SOURCE,
            retrieved_at=now,
            available_at=now,
            period_start=None,
            period_end=None,
            validation_status=ValidationStatus.VALID if tickers else ValidationStatus.INSUFFICIENT,
        )

    def list_companies(self) -> SourcedValue[list[CompanyRecord]]:
        now = dt.datetime.now(dt.UTC)
        payload = self._get("/stocks", {"exchange": "IDX"})
        rows = payload.get("data", [])
        companies = [
            CompanyRecord(
                ticker=row["symbol"],
                company_name=row["name"],
                asset_type=row.get("type"),
            )
            for row in rows
            if row.get("symbol") and row.get("name")
        ]
        return SourcedValue(
            value=companies,
            source=_SOURCE,
            retrieved_at=now,
            available_at=now,
            period_start=None,
            period_end=None,
            validation_status=ValidationStatus.VALID if companies else ValidationStatus.INSUFFICIENT,
        )

    def get_ohlcv(self, ticker: str, start: dt.date, end: dt.date) -> SourcedValue[list[OHLCVBar]]:
        now = dt.datetime.now(dt.UTC)
        payload = self._get(
            "/time_series",
            {
                "symbol": ticker,
                "exchange": "IDX",
                "interval": "1day",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "outputsize": 5000,
            },
        )
        values = payload.get("values", []) if isinstance(payload, dict) else []
        bars = [
            OHLCVBar(
                trade_date=dt.date.fromisoformat(row["datetime"]),
                open=_to_float(row.get("open")),
                high=_to_float(row.get("high")),
                low=_to_float(row.get("low")),
                close=_to_float(row.get("close")),
                volume=_to_int(row.get("volume")),
            )
            for row in values
        ]
        bars.sort(key=lambda b: b.trade_date)
        return SourcedValue(
            value=bars,
            # EOD data; Twelve Data does not return a per-bar publish
            # timestamp, so retrieval time is used as a conservative
            # (never-too-early) stand-in for available_at.
            source=_SOURCE,
            retrieved_at=now,
            available_at=now,
            period_start=start,
            period_end=end,
            validation_status=ValidationStatus.VALID if bars else ValidationStatus.INSUFFICIENT,
        )

    def get_corporate_actions(self, ticker: str, start: dt.date, end: dt.date) -> SourcedValue[list[dict]]:
        raise NotImplementedError(
            "Twelve Data corporate-actions endpoint not yet verified against a live "
            "response -- see this module's docstring. Do not guess the contract."
        )


def _to_float(value) -> float | None:
    return float(value) if value not in (None, "") else None


def _to_int(value) -> int | None:
    return int(float(value)) if value not in (None, "") else None
