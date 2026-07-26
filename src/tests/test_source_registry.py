"""Pure/mocked unit tests for the data source capability probe
(``src/data_sources/registry.py``, master-prompt "Section B"). All HTTP
calls mocked with respx -- same convention as ``test_market_adapters.py``.
"""
from __future__ import annotations

import httpx
import respx

from src.data_sources.registry import SourceCatalogEntry, probe_source
from src.database.models.ops import AuthorityLevel, SourceHealthStatus, SourceType, SourceUsageMode


def _entry(**overrides) -> SourceCatalogEntry:
    defaults = {
        "source_code": "test_source", "source_name": "Test Source", "base_url": "https://example.invalid/probe",
        "source_type": SourceType.HTML, "data_category": "macro",
        "authority_level": AuthorityLevel.REGULATOR, "usage_mode": SourceUsageMode.LICENSE_REVIEW,
        "official_status": "official", "license_status": "review_required", "access_method": "http_get",
    }
    defaults.update(overrides)
    return SourceCatalogEntry(**defaults)


class _FakeSettings:
    bps_api_key = None
    fred_api_key = None


@respx.mock
def test_probe_healthy_when_200_and_marker_present():
    respx.get("https://example.invalid/probe").mock(
        return_value=httpx.Response(200, text="x" * 300 + "<rss>real feed content</rss>")
    )
    entry = _entry(content_marker="<rss")
    status, reason = probe_source(entry, _FakeSettings())
    assert status == SourceHealthStatus.HEALTHY
    assert reason is None


@respx.mock
def test_probe_empty_when_200_but_body_too_small():
    respx.get("https://example.invalid/probe").mock(return_value=httpx.Response(200, text="ok"))
    entry = _entry()
    status, reason = probe_source(entry, _FakeSettings())
    assert status == SourceHealthStatus.EMPTY
    assert "bytes" in reason


@respx.mock
def test_probe_format_changed_when_marker_missing():
    respx.get("https://example.invalid/probe").mock(return_value=httpx.Response(200, text="x" * 300))
    entry = _entry(content_marker="<rss")
    status, reason = probe_source(entry, _FakeSettings())
    assert status == SourceHealthStatus.FORMAT_CHANGED
    assert "<rss" in reason


@respx.mock
def test_probe_blocked_on_403():
    respx.get("https://example.invalid/probe").mock(return_value=httpx.Response(403, text="Forbidden"))
    entry = _entry()
    status, _reason = probe_source(entry, _FakeSettings())
    assert status == SourceHealthStatus.BLOCKED


@respx.mock
def test_probe_rate_limited_on_429():
    respx.get("https://example.invalid/probe").mock(return_value=httpx.Response(429, text="Too Many Requests"))
    entry = _entry()
    status, _reason = probe_source(entry, _FakeSettings())
    assert status == SourceHealthStatus.RATE_LIMITED


@respx.mock
def test_probe_authentication_required_on_401():
    respx.get("https://example.invalid/probe").mock(return_value=httpx.Response(401, text="Unauthorized"))
    entry = _entry()
    status, _reason = probe_source(entry, _FakeSettings())
    assert status == SourceHealthStatus.AUTHENTICATION_REQUIRED


def test_probe_unverified_when_api_key_required_but_missing():
    entry = _entry(requires_api_key=True, api_key_setting="bps_api_key")
    status, reason = probe_source(entry, _FakeSettings())
    assert status == SourceHealthStatus.UNVERIFIED
    assert "bps_api_key" in reason


@respx.mock
def test_probe_url_substitutes_api_key_placeholder():
    respx.get("https://example.invalid/probe?key=SECRET123").mock(
        return_value=httpx.Response(200, text="x" * 300)
    )
    entry = _entry(
        probe_url="https://example.invalid/probe?key={api_key}", requires_api_key=True, api_key_setting="bps_api_key",
    )

    class _KeyedSettings:
        bps_api_key = "SECRET123"

    status, _ = probe_source(entry, _KeyedSettings())
    assert status == SourceHealthStatus.HEALTHY
