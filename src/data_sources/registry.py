"""Data source capability/health-check registry (master-prompt "Section
B"). Two concerns kept separate on purpose:

- ``SOURCE_CATALOG`` -- static, code-defined metadata (type, authority,
  usage mode, how to probe it) for every real or candidate source this
  project uses or is evaluating. Adding a source here does not mean it's
  trusted -- ``usage_mode``/``health_status`` say that.
- ``data_sources`` (``DataSourceCapability``) -- the DB table storing the
  *last real audit result* for each catalog entry. ``sync_catalog``
  upserts the static fields; ``run_audit`` does a real network probe per
  source and updates only the health fields.

A probe is never satisfied by "HTTP 200" alone (master prompt rule: an
empty 200 must not count as success) -- every entry needs either a
minimum-body-size check (default) or an explicit ``content_marker``
substring that must appear in a real successful response.
"""
from __future__ import annotations

import dataclasses
import datetime as dt

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.database.models.ops import (
    AuthorityLevel,
    DataSourceCapability,
    SourceHealthStatus,
    SourceType,
    SourceUsageMode,
)

_MIN_BODY_BYTES = 200  # a real page/feed/API payload is never this small; catches "200 OK, empty body" (rule: HTTP 200 with empty content is not success)
_USER_AGENT = "Mozilla/5.0 (compatible; IDXInvestmentIntelligence/1.0; +research, non-commercial)"


@dataclasses.dataclass(frozen=True)
class SourceCatalogEntry:
    source_code: str
    source_name: str
    base_url: str
    source_type: SourceType
    data_category: str
    authority_level: AuthorityLevel
    usage_mode: SourceUsageMode
    official_status: str
    license_status: str
    access_method: str
    requires_api_key: bool = False
    supports_history: bool = False
    supports_incremental: bool = False
    supports_commercial_use: bool = False
    probe_url: str | None = None  # overrides base_url for the health probe itself, if different
    content_marker: str | None = None  # substring required in a real successful response body
    api_key_setting: str | None = None  # Settings attribute name, if requires_api_key


SOURCE_CATALOG: list[SourceCatalogEntry] = [
    # --- already implemented, in production use ---
    SourceCatalogEntry(
        source_code="yahoo_finance_market", source_name="Yahoo Finance (OHLCV, research-only)",
        base_url="https://finance.yahoo.com", source_type=SourceType.API, data_category="market",
        authority_level=AuthorityLevel.AGGREGATOR, usage_mode=SourceUsageMode.RESEARCH_ONLY,
        official_status="unofficial", license_status="review_required", access_method="http_get",
        supports_history=True, supports_incremental=True,
        probe_url="https://query1.finance.yahoo.com/v8/finance/chart/BBCA.JK", content_marker='"chart"',
    ),
    SourceCatalogEntry(
        source_code="yahoo_finance_fundamentals", source_name="Yahoo Finance (financial statements, research-only)",
        base_url="https://finance.yahoo.com", source_type=SourceType.API, data_category="fundamentals",
        authority_level=AuthorityLevel.AGGREGATOR, usage_mode=SourceUsageMode.RESEARCH_ONLY,
        official_status="unofficial", license_status="review_required", access_method="http_get",
        supports_history=True, supports_incremental=True,
        probe_url="https://query1.finance.yahoo.com/v8/finance/chart/BBCA.JK", content_marker='"chart"',
    ),
    SourceCatalogEntry(
        source_code="yahoo_finance_macro", source_name="Yahoo Finance (FX/index/commodity/yield, research-only)",
        base_url="https://finance.yahoo.com", source_type=SourceType.API, data_category="macro",
        authority_level=AuthorityLevel.AGGREGATOR, usage_mode=SourceUsageMode.RESEARCH_ONLY,
        official_status="unofficial", license_status="review_required", access_method="http_get",
        supports_history=True, supports_incremental=True,
        probe_url="https://query1.finance.yahoo.com/v8/finance/chart/USDIDR=X", content_marker='"chart"',
    ),
    SourceCatalogEntry(
        source_code="twelve_data", source_name="Twelve Data (OHLCV, capability-gated)",
        base_url="https://api.twelvedata.com", source_type=SourceType.API, data_category="market",
        authority_level=AuthorityLevel.AGGREGATOR, usage_mode=SourceUsageMode.VERIFICATION_ONLY,
        official_status="unofficial", license_status="review_required", access_method="api_key",
        requires_api_key=True, api_key_setting="twelve_data_api_key",
        supports_history=True, supports_incremental=True,
        probe_url="https://api.twelvedata.com/time_series?symbol=BBCA&exchange=IDX&interval=1day&outputsize=1&apikey=demo",
        content_marker=None,
    ),
    SourceCatalogEntry(
        source_code="bps_webapi", source_name="BPS (Statistik Indonesia) Web API",
        base_url="https://webapi.bps.go.id/v1/api", source_type=SourceType.API, data_category="macro",
        authority_level=AuthorityLevel.GOVERNMENT, usage_mode=SourceUsageMode.PRODUCTION_ALLOWED,
        official_status="official", license_status="public", access_method="api_key",
        requires_api_key=True, api_key_setting="bps_api_key",
        supports_history=True, supports_incremental=True,
        # {api_key} substituted at probe time -- the bare base_url alone
        # 404s (real finding: "index" action not recognized without a
        # real endpoint path), this is the real lightweight subject-
        # catalog call the working bps.py adapter already uses.
        probe_url="https://webapi.bps.go.id/v1/api/list/model/subject/domain/0000/key/{api_key}",
        content_marker='"status"',
    ),
    SourceCatalogEntry(
        source_code="antara_ekonomi_rss", source_name="ANTARA Ekonomi RSS",
        base_url="https://www.antaranews.com/rss/ekonomi.xml", source_type=SourceType.RSS, data_category="news",
        authority_level=AuthorityLevel.NEWS_AGENCY, usage_mode=SourceUsageMode.PRODUCTION_ALLOWED,
        official_status="unofficial", license_status="public", access_method="rss",
        supports_history=False, supports_incremental=True, content_marker="<rss",
    ),
    SourceCatalogEntry(
        source_code="cnbc_indonesia_market_rss", source_name="CNBC Indonesia Market RSS",
        base_url="https://www.cnbcindonesia.com/market/rss", source_type=SourceType.RSS, data_category="news",
        authority_level=AuthorityLevel.BUSINESS_MEDIA, usage_mode=SourceUsageMode.PRODUCTION_ALLOWED,
        official_status="unofficial", license_status="public", access_method="rss",
        supports_history=False, supports_incremental=True, content_marker="<rss",
    ),
    SourceCatalogEntry(
        source_code="detik_finance_rss", source_name="Detik Finance RSS",
        base_url="https://finance.detik.com/rss", source_type=SourceType.RSS, data_category="news",
        authority_level=AuthorityLevel.BUSINESS_MEDIA, usage_mode=SourceUsageMode.PRODUCTION_ALLOWED,
        official_status="unofficial", license_status="public", access_method="rss",
        supports_history=False, supports_incremental=True, content_marker="<rss",
    ),
    SourceCatalogEntry(
        source_code="katadata_rss", source_name="Katadata RSS",
        base_url="https://katadata.co.id/rss", source_type=SourceType.RSS, data_category="news",
        authority_level=AuthorityLevel.BUSINESS_MEDIA, usage_mode=SourceUsageMode.PRODUCTION_ALLOWED,
        official_status="unofficial", license_status="public", access_method="rss",
        supports_history=False, supports_incremental=True, content_marker="<rss",
    ),
    SourceCatalogEntry(
        source_code="huggingface_sentiment_model",
        source_name="ayameRushia/bert-base-indonesian-1.5G-sentiment-analysis-smsa (HuggingFace)",
        base_url="https://huggingface.co/ayameRushia/bert-base-indonesian-1.5G-sentiment-analysis-smsa",
        source_type=SourceType.DOCUMENT_REPOSITORY, data_category="news",
        authority_level=AuthorityLevel.AGGREGATOR, usage_mode=SourceUsageMode.RESEARCH_ONLY,
        official_status="unofficial", license_status="review_required", access_method="http_get",
        content_marker=None,
    ),
    # --- Section D candidates: real Indonesia macro sources, checked live as part of this audit ---
    SourceCatalogEntry(
        source_code="bi_rate_html", source_name="Bank Indonesia -- BI-Rate (official HTML table)",
        base_url="https://www.bi.go.id/id/statistik/indikator/bi-rate.aspx",
        source_type=SourceType.HTML, data_category="macro",
        authority_level=AuthorityLevel.REGULATOR, usage_mode=SourceUsageMode.LICENSE_REVIEW,
        official_status="official", license_status="review_required", access_method="http_get",
        supports_history=True, supports_incremental=True, content_marker=None,
    ),
    SourceCatalogEntry(
        source_code="bi_jisdor", source_name="Bank Indonesia -- JISDOR USD/IDR reference rate",
        base_url="https://www.bi.go.id/id/statistik/informasi-kurs/jisdor/default.aspx",
        source_type=SourceType.HTML, data_category="macro",
        authority_level=AuthorityLevel.REGULATOR, usage_mode=SourceUsageMode.LICENSE_REVIEW,
        official_status="official", license_status="review_required", access_method="http_get",
        supports_history=True, supports_incremental=True, content_marker=None,
    ),
    SourceCatalogEntry(
        source_code="bi_seki", source_name="Bank Indonesia -- SEKI (Statistik Ekonomi Keuangan Indonesia)",
        base_url="https://www.bi.go.id/id/statistik/ekonomi-keuangan/seki/default.aspx",
        source_type=SourceType.HTML, data_category="macro",
        authority_level=AuthorityLevel.REGULATOR, usage_mode=SourceUsageMode.LICENSE_REVIEW,
        official_status="official", license_status="review_required", access_method="file_download",
        supports_history=True, content_marker=None,
    ),
    SourceCatalogEntry(
        source_code="bi_sdds", source_name="Bank Indonesia -- SDDS",
        base_url="https://www.bi.go.id/en/statistik/sdds/default.aspx",
        source_type=SourceType.HTML, data_category="macro",
        authority_level=AuthorityLevel.REGULATOR, usage_mode=SourceUsageMode.LICENSE_REVIEW,
        official_status="official", license_status="review_required", access_method="file_download",
        supports_history=True, content_marker=None,
    ),
    SourceCatalogEntry(
        source_code="bi_indonia", source_name="Bank Indonesia -- INDONIA (IndONIA overnight rate)",
        base_url="https://www.bi.go.id/id/fungsi-utama/moneter/indonia-jibor/default.aspx",
        source_type=SourceType.HTML, data_category="macro",
        authority_level=AuthorityLevel.REGULATOR, usage_mode=SourceUsageMode.LICENSE_REVIEW,
        official_status="official", license_status="review_required", access_method="file_download",
        supports_history=True, content_marker=None,
    ),
    SourceCatalogEntry(
        source_code="world_bank_indicators", source_name="World Bank Indicators API",
        base_url="https://api.worldbank.org/v2", source_type=SourceType.API, data_category="macro",
        authority_level=AuthorityLevel.INTERNATIONAL_INSTITUTION, usage_mode=SourceUsageMode.RESEARCH_ONLY,
        official_status="official", license_status="public", access_method="http_get",
        supports_history=True,
        probe_url="https://api.worldbank.org/v2/country/ID/indicator/FP.CPI.TOTL.ZG?format=json&per_page=1",
        content_marker=None,
    ),
    SourceCatalogEntry(
        source_code="imf_sdmx", source_name="IMF SDMX API",
        base_url="https://api.imf.org/external/sdmx/3.0", source_type=SourceType.API, data_category="macro",
        authority_level=AuthorityLevel.INTERNATIONAL_INSTITUTION, usage_mode=SourceUsageMode.RESEARCH_ONLY,
        official_status="official", license_status="public", access_method="http_get",
        supports_history=True,
        # the bare base_url 404s (real finding) -- this is the real
        # structure/dataflow catalog endpoint, verified live.
        probe_url="https://api.imf.org/external/sdmx/3.0/structure/dataflow/IMF.STA",
        content_marker='"dataflows"',
    ),
    SourceCatalogEntry(
        source_code="fred", source_name="FRED (Federal Reserve Economic Data)",
        base_url="https://api.stlouisfed.org/fred", source_type=SourceType.API, data_category="macro",
        authority_level=AuthorityLevel.GOVERNMENT, usage_mode=SourceUsageMode.RESEARCH_ONLY,
        official_status="official", license_status="public", access_method="api_key",
        requires_api_key=True, api_key_setting="fred_api_key", supports_history=True,
        content_marker=None,
    ),
]

_CATALOG_BY_CODE = {entry.source_code: entry for entry in SOURCE_CATALOG}


def sync_catalog(session: Session) -> int:
    """Upsert every catalog entry's static metadata into ``data_sources``.
    Never touches health fields -- those only ever change via a real
    ``run_audit`` probe."""
    written = 0
    for entry in SOURCE_CATALOG:
        row = session.scalar(select(DataSourceCapability).where(DataSourceCapability.source_code == entry.source_code))
        if row is None:
            row = DataSourceCapability(source_code=entry.source_code, health_status=SourceHealthStatus.UNVERIFIED)
            session.add(row)
        row.source_name = entry.source_name
        row.base_url = entry.base_url
        row.source_type = entry.source_type
        row.data_category = entry.data_category
        row.authority_level = entry.authority_level
        row.usage_mode = entry.usage_mode
        row.official_status = entry.official_status
        row.license_status = entry.license_status
        row.access_method = entry.access_method
        row.requires_api_key = entry.requires_api_key
        row.supports_history = entry.supports_history
        row.supports_incremental = entry.supports_incremental
        row.supports_commercial_use = entry.supports_commercial_use
        written += 1
    return written


def probe_source(entry: SourceCatalogEntry, settings: Settings, client: httpx.Client | None = None) -> tuple[SourceHealthStatus, str | None]:
    """Real network probe -- never assume HTTP 200 == success. Returns
    (health_status, failure_reason)."""
    key = None
    if entry.requires_api_key:
        key = getattr(settings, entry.api_key_setting, None) if entry.api_key_setting else None
        if not key and entry.source_code != "twelve_data":  # twelve_data's probe URL uses the public "demo" key deliberately
            return SourceHealthStatus.UNVERIFIED, f"no {entry.api_key_setting} configured -- cannot probe"

    url = entry.probe_url or entry.base_url
    if key and "{api_key}" in url:
        url = url.format(api_key=key)
    owns_client = client is None
    client = client or httpx.Client(timeout=20.0, follow_redirects=True, headers={"User-Agent": _USER_AGENT})
    try:
        response = client.get(url)
    except httpx.TimeoutException:
        return SourceHealthStatus.DEGRADED, "request timed out"
    except httpx.HTTPError as exc:
        return SourceHealthStatus.BLOCKED, f"request failed: {exc}"
    finally:
        if owns_client:
            client.close()

    if response.status_code == 401:
        return SourceHealthStatus.AUTHENTICATION_REQUIRED, f"HTTP 401: {response.text[:200]!r}"
    if response.status_code == 429:
        return SourceHealthStatus.RATE_LIMITED, f"HTTP 429: {response.text[:200]!r}"
    if response.status_code >= 400:
        return SourceHealthStatus.BLOCKED, f"HTTP {response.status_code}: {response.text[:200]!r}"

    body = response.content
    if len(body) < _MIN_BODY_BYTES:
        return SourceHealthStatus.EMPTY, f"HTTP 200 but body only {len(body)} bytes -- not treated as success"
    if entry.content_marker and entry.content_marker not in response.text:
        return (
            SourceHealthStatus.FORMAT_CHANGED,
            f"HTTP 200, {len(body)} bytes, but expected marker {entry.content_marker!r} not found -- page structure may have changed",
        )
    return SourceHealthStatus.HEALTHY, None


def run_audit(
    session: Session, settings: Settings, category: str | None = None, client: httpx.Client | None = None
) -> list[tuple[str, SourceHealthStatus, str | None]]:
    """Probe every catalog entry (optionally filtered by data_category)
    that has a corresponding ``data_sources`` row, and persist the result.
    Returns [(source_code, health_status, failure_reason), ...]."""
    stmt = select(DataSourceCapability)
    if category:
        stmt = stmt.where(DataSourceCapability.data_category == category)
    rows = session.scalars(stmt).all()

    owns_client = client is None
    client = client or httpx.Client(timeout=20.0, follow_redirects=True, headers={"User-Agent": _USER_AGENT})
    results: list[tuple[str, SourceHealthStatus, str | None]] = []
    try:
        for row in rows:
            entry = _CATALOG_BY_CODE.get(row.source_code)
            if entry is None:
                continue
            now = dt.datetime.now(dt.UTC)
            status, reason = probe_source(entry, settings, client=client)
            row.health_status = status
            row.checked_at = now
            row.failure_reason = reason
            if status == SourceHealthStatus.HEALTHY:
                row.last_success_at = now
            elif status != SourceHealthStatus.UNVERIFIED:
                row.last_failure_at = now
            results.append((row.source_code, status, reason))
    finally:
        if owns_client:
            client.close()
    return results
