"""Unit tests for retry/circuit-breaker/rate-limiter."""
from __future__ import annotations

import pytest

from src.data_sources.base import ProviderUnavailableError
from src.data_sources.market.capability import ProviderInvalidKeyError
from src.ingestion.resilience import CircuitBreaker, CircuitBreakerOpenError, RateLimiter, with_retry


def test_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    @with_retry(max_retries=5)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ProviderUnavailableError("transient")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3


def test_retry_gives_up_after_max_attempts():
    calls = {"n": 0}

    @with_retry(max_retries=3)
    def always_fails():
        calls["n"] += 1
        raise ProviderUnavailableError("still down")

    with pytest.raises(ProviderUnavailableError):
        always_fails()
    assert calls["n"] == 3


def test_retry_does_not_retry_invalid_key():
    calls = {"n": 0}

    @with_retry(max_retries=5)
    def bad_key():
        calls["n"] += 1
        raise ProviderInvalidKeyError("bad key")

    with pytest.raises(ProviderInvalidKeyError):
        bad_key()
    assert calls["n"] == 1  # no retry -- permission errors aren't retryable


def test_circuit_breaker_opens_after_threshold():
    breaker = CircuitBreaker(failure_threshold=3)
    for _ in range(3):
        breaker.record_failure()
    assert breaker.is_open
    with pytest.raises(CircuitBreakerOpenError):
        breaker.check()


def test_circuit_breaker_resets_on_success():
    breaker = CircuitBreaker(failure_threshold=3)
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    breaker.record_failure()
    assert not breaker.is_open  # only 2 consecutive since the reset


def test_rate_limiter_first_call_does_not_block():
    limiter = RateLimiter(delay_seconds=10)
    import time

    start = time.monotonic()
    limiter.wait()
    assert time.monotonic() - start < 0.5
