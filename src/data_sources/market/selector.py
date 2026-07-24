"""Market-data provider selection (spec: auto mode, research vs. production
guardrail).

The whole point of this module: **never silently fall back**. Every
selection logs which provider was chosen and why (capability status), and
every fallback to a non-official/non-licensed provider is an explicit,
visible decision -- never a quiet default.
"""
from __future__ import annotations

import datetime as dt
import logging

from src.data_sources.market.base import MarketDataProvider
from src.data_sources.market.capability import (  # noqa: F401 -- re-exported for callers of this module
    ProviderAccessError,
    ProviderCapability,
    ProviderInvalidKeyError,
    ProviderPlanNotSupportedError,
    ProviderRateLimitError,
    probe_twelve_data_ohlcv_capability,
)

logger = logging.getLogger(__name__)


class NoLicensedProviderAvailableError(ProviderAccessError):
    """Raised in production mode when no provider with commercial/production
    rights is available -- spec: production mode must refuse research-only
    providers, not silently use them."""


def yahoo_finance_capability(status: str = "available", failure_reason: str | None = None) -> ProviderCapability:
    return ProviderCapability(
        provider_name="yahoo_finance",
        asset_class="equity",
        market="IDX",
        capability="ohlcv",
        access_level="free",
        usage_mode="research",
        is_official=False,
        supports_historical=True,
        supports_adjusted_price=True,
        supports_dividends=True,
        supports_splits=True,
        supports_commercial_use=False,
        status=status,
        last_checked_at=dt.datetime.now(dt.UTC),
        failure_reason=failure_reason,
    )


class MarketDataProviderSelector:
    """Implements ``MARKET_DATA_PROVIDER=auto`` (spec section 2): probe
    Twelve Data first, fall back to Yahoo Finance in research mode only,
    refuse to select an unlicensed provider in production mode."""

    def __init__(
        self,
        twelve_data_provider: MarketDataProvider,
        yahoo_provider: MarketDataProvider,
        twelve_data_api_key: str | None,
        configured_provider: str,  # "auto" | "twelve_data" | "yahoo_finance"
        usage_mode: str,  # "research" | "production"
        enable_yahoo_fallback: bool,
    ) -> None:
        self._twelve_data_provider = twelve_data_provider
        self._yahoo_provider = yahoo_provider
        self._twelve_data_api_key = twelve_data_api_key
        self._configured_provider = configured_provider
        self._usage_mode = usage_mode
        self._enable_yahoo_fallback = enable_yahoo_fallback

    def select(self, probe_ticker: str) -> tuple[MarketDataProvider, ProviderCapability]:
        if self._configured_provider == "twelve_data":
            capability = probe_twelve_data_ohlcv_capability(self._twelve_data_api_key, probe_ticker)
            if capability.status != "available":
                raise ProviderAccessError(
                    f"MARKET_DATA_PROVIDER=twelve_data forced, but capability probe failed: "
                    f"status={capability.status} reason={capability.failure_reason}"
                )
            logger.info("market_data_provider_selected", extra={"provider": "twelve_data", "forced": True})
            return self._twelve_data_provider, capability

        if self._configured_provider == "yahoo_finance":
            if self._usage_mode == "production":
                raise NoLicensedProviderAvailableError(
                    "MARKET_DATA_PROVIDER=yahoo_finance forced, but MARKET_DATA_USAGE_MODE=production "
                    "forbids research-only providers (spec production guardrail)."
                )
            capability = yahoo_finance_capability()
            logger.info("market_data_provider_selected", extra={"provider": "yahoo_finance", "forced": True})
            return self._yahoo_provider, capability

        if self._configured_provider != "auto":
            raise ValueError(f"Unknown MARKET_DATA_PROVIDER: {self._configured_provider!r}")

        # auto mode
        capability = probe_twelve_data_ohlcv_capability(self._twelve_data_api_key, probe_ticker)
        if capability.status == "available":
            logger.info(
                "market_data_provider_selected",
                extra={"provider": "twelve_data", "mode": "auto", "capability_status": capability.status},
            )
            return self._twelve_data_provider, capability

        logger.warning(
            "market_data_provider_twelve_data_unavailable",
            extra={"status": capability.status, "reason": capability.failure_reason},
        )

        if self._usage_mode == "production":
            raise NoLicensedProviderAvailableError(
                f"MARKET_DATA_USAGE_MODE=production and Twelve Data is unavailable "
                f"(status={capability.status}, reason={capability.failure_reason}). "
                f"Research-only providers (Yahoo Finance) cannot be used in production mode."
            )

        if not self._enable_yahoo_fallback:
            raise ProviderAccessError(
                f"Twelve Data unavailable (status={capability.status}) and "
                f"ENABLE_YAHOO_FINANCE_FALLBACK=false -- no provider to use."
            )

        yahoo_capability = yahoo_finance_capability()
        logger.warning(
            "market_data_provider_fallback",
            extra={
                "from_provider": "twelve_data",
                "from_status": capability.status,
                "to_provider": "yahoo_finance",
                "to_usage_restriction": "research_only",
            },
        )
        return self._yahoo_provider, yahoo_capability
