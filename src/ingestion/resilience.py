"""Rate limiting, retry, and circuit-breaking for OHLCV ingestion (spec
section 10). Centralized here rather than inside each adapter, so retry
policy is one configurable thing, not N slightly-different copies.
"""
from __future__ import annotations

import logging
import time

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from src.data_sources.base import ProviderUnavailableError
from src.data_sources.market.capability import ProviderInvalidKeyError, ProviderPlanNotSupportedError

logger = logging.getLogger(__name__)

_NON_RETRYABLE = (ProviderInvalidKeyError, ProviderPlanNotSupportedError)


def _is_retryable(exc: BaseException) -> bool:
    """Retry transport failures and rate limits; never retry a permission
    problem (invalid key, plan restriction) -- another attempt can't fix
    those, it just wastes the retry budget."""
    if isinstance(exc, _NON_RETRYABLE):
        return False
    return isinstance(exc, ProviderUnavailableError)


def with_retry(max_retries: int):
    """Exponential backoff + jitter, capped attempts -- never retries
    forever (spec: "Jangan melakukan retry tanpa batas")."""
    return retry(
        reraise=True,
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential_jitter(initial=1, max=30),
        retry=retry_if_exception(_is_retryable),
    )


class RateLimiter:
    """Simple fixed-delay pacer between calls to one provider -- not a
    token bucket, just "don't hammer a free-tier API." Good enough at the
    request volumes this project makes; revisit if a provider's real rate
    limit needs more precision than a flat delay."""

    def __init__(self, delay_seconds: float) -> None:
        self._delay = delay_seconds
        self._last_call: float | None = None

    def wait(self) -> None:
        if self._delay <= 0 or self._last_call is None:
            self._last_call = time.monotonic()
            return
        elapsed = time.monotonic() - self._last_call
        remaining = self._delay - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_call = time.monotonic()


class CircuitBreakerOpenError(ProviderUnavailableError):
    pass


class CircuitBreaker:
    """Stops calling a provider for the rest of a run after too many
    consecutive failures -- avoids burning through a whole ticker list one
    slow timeout at a time when a provider is already down."""

    def __init__(self, failure_threshold: int = 5) -> None:
        self._threshold = failure_threshold
        self._consecutive_failures = 0
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def record_success(self) -> None:
        self._consecutive_failures = 0

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._threshold:
            if not self._open:
                logger.warning(
                    "circuit_breaker_opened",
                    extra={"consecutive_failures": self._consecutive_failures},
                )
            self._open = True

    def check(self) -> None:
        if self._open:
            raise CircuitBreakerOpenError(
                f"circuit breaker open after {self._consecutive_failures} consecutive failures"
            )
