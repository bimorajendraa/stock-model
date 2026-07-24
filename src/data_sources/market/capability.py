"""Provider capability detection for market-data OHLCV (spec: multi-provider
capability system).

The core rule this module exists to enforce: **an API key existing does not
mean the endpoint can be used.** Twelve Data's free/Basic plan tier is not
guaranteed to include Indonesia Stock Exchange (XIDX) OHLCV -- the only way
to know is to actually call the endpoint against a real symbol and inspect
the response, not just check for HTTP 200.

Error classification below (invalid key vs. plan-restricted vs. rate
limited vs. symbol-not-found vs. generic failure) is built from Twelve
Data's documented conventions and the one live response this project
*could* verify (the public ``demo`` key, which returns HTTP 200 + a
``code: 401`` "familiarity only" body for ``/time_series``). The exact
wording of a real *plan-restriction* response (a paid/free-registered key
whose plan excludes XIDX) has not been observed live -- no such key was
available while writing this. Classification below matches on status code
first and message keywords second, deliberately loose rather than an exact
string match, so it degrades to ``ProviderAccessError`` (generic) instead
of silently misclassifying if Twelve Data's wording differs from what's
guessed here. Tighten this once a real restricted-plan response is seen.
"""
from __future__ import annotations

import dataclasses
import datetime as dt

import httpx

from src.data_sources.base import ProviderUnavailableError


class ProviderAccessError(ProviderUnavailableError):
    """Base class for all provider-access (permission/plan/key) failures
    the capability probe can classify. Subclasses ``ProviderUnavailableError``
    so existing ``except ProviderUnavailableError`` handlers in ingestion
    code (spec §33 fallback behavior) still catch these without change --
    while callers that care about *why* can catch the specific subtype."""


class ProviderInvalidKeyError(ProviderAccessError):
    pass


class ProviderPlanNotSupportedError(ProviderAccessError):
    pass


class ProviderRateLimitError(ProviderAccessError):
    pass


class ProviderSymbolNotFoundError(ProviderAccessError):
    pass


@dataclasses.dataclass
class ProviderCapability:
    provider_name: str
    asset_class: str
    market: str
    capability: str
    access_level: str  # "free" | "paid" | "unknown"
    usage_mode: str  # "research" | "production"
    is_official: bool
    supports_historical: bool
    supports_adjusted_price: bool
    supports_dividends: bool
    supports_splits: bool
    supports_commercial_use: bool
    status: str
    # "available" | "capability_probe_required" | "plan_restricted" |
    # "invalid_key" | "rate_limited" | "unavailable" | "error"
    last_checked_at: dt.datetime | None
    failure_reason: str | None = None


def is_twelve_data_error_payload(payload: dict) -> bool:
    """Twelve Data is inconsistent about error shape: some paths return
    {"status": "error", ...}; the demo-key-specific message (verified live
    on 2026-07-24) is {"code": 401, "message": ...} with NO "status" key at
    all. Treat anything code+message-shaped that lacks the expected
    success keys as an error too."""
    return isinstance(payload, dict) and (
        payload.get("status") == "error"
        or ("code" in payload and "message" in payload and not any(k in payload for k in ("values", "data")))
    )


def classify_twelve_data_error(status_code: int, payload: dict) -> ProviderAccessError:
    """Turn a Twelve Data error response into a specific exception.

    See module docstring: status code is authoritative, message keywords
    are a best-effort secondary signal.
    """
    code = payload.get("code", status_code)
    message = str(payload.get("message", "")).lower()

    if status_code == 429 or code == 429 or "rate limit" in message:
        return ProviderRateLimitError(f"rate limited: {message or status_code}")
    if status_code == 401 or code == 401 or ("invalid" in message and "key" in message) or "demo" in message:
        return ProviderInvalidKeyError(f"invalid or demo API key: {message or status_code}")
    if status_code == 403 or code == 403 or any(k in message for k in ("plan", "subscribe", "upgrade", "not available")):
        return ProviderPlanNotSupportedError(f"plan does not support this market/endpoint: {message or status_code}")
    if status_code == 400 and any(k in message for k in ("not found", "does not exist", "no data")):
        return ProviderSymbolNotFoundError(f"symbol not found: {message or status_code}")
    return ProviderAccessError(f"twelve_data error (status={status_code}, code={code}): {message}")


def probe_twelve_data_ohlcv_capability(
    api_key: str | None,
    probe_ticker: str,
    client: httpx.Client | None = None,
) -> ProviderCapability:
    """Actually call Twelve Data's /time_series for one real IDX ticker and
    inspect the response -- never assume "key present" == "usable"."""
    now = dt.datetime.now(dt.UTC)
    base = {
        "provider_name": "twelve_data",
        "asset_class": "equity",
        "market": "IDX",
        "capability": "ohlcv",
        "access_level": "unknown",
        "usage_mode": "research",
        "is_official": False,
        "supports_historical": True,
        "supports_adjusted_price": False,
        "supports_dividends": False,
        "supports_splits": False,
        "supports_commercial_use": False,
        "last_checked_at": now,
    }

    if not api_key:
        return ProviderCapability(
            **base, status="capability_probe_required", failure_reason="no TWELVE_DATA_API_KEY configured"
        )

    owns_client = client is None
    client = client or httpx.Client(base_url="https://api.twelvedata.com", timeout=15.0)
    try:
        end = dt.datetime.now(dt.UTC).date()
        start = end - dt.timedelta(days=5)
        response = client.get(
            "/time_series",
            params={
                "symbol": probe_ticker,
                "exchange": "IDX",
                "interval": "1day",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "outputsize": 5,
                "apikey": api_key,
            },
        )
    except httpx.HTTPError as exc:
        return ProviderCapability(**base, status="error", failure_reason=f"request failed: {exc}")
    finally:
        if owns_client:
            client.close()

    try:
        payload = response.json()
    except ValueError:
        return ProviderCapability(**base, status="error", failure_reason="non-JSON response")

    if response.status_code >= 400 or is_twelve_data_error_payload(payload):
        try:
            raise classify_twelve_data_error(response.status_code, payload if isinstance(payload, dict) else {})
        except ProviderInvalidKeyError as exc:
            return ProviderCapability(**base, status="invalid_key", failure_reason=str(exc))
        except ProviderPlanNotSupportedError as exc:
            return ProviderCapability(**base, status="plan_restricted", failure_reason=str(exc))
        except ProviderRateLimitError as exc:
            return ProviderCapability(**base, status="rate_limited", failure_reason=str(exc))
        except ProviderSymbolNotFoundError as exc:
            return ProviderCapability(**base, status="error", failure_reason=str(exc))
        except ProviderAccessError as exc:
            return ProviderCapability(**base, status="error", failure_reason=str(exc))

    values = payload.get("values") if isinstance(payload, dict) else None
    if not values:
        return ProviderCapability(
            **base, status="error", failure_reason=f"200 OK but no OHLCV values in response: {payload!r:.200}"
        )

    return ProviderCapability(
        **{**base, "access_level": "paid_or_free_confirmed", "supports_adjusted_price": False},
        status="available",
        failure_reason=None,
    )
