"""RSS feed adapter for Indonesian financial news (spec section 3.6) --
real, standard RSS 2.0 feeds, parsed with the stdlib XML parser (no new
dependency).

**What was actually investigated (2026-07-25), live, before writing any
code** (spec section 2.2: never a fabricated/guessed source):

| Candidate | Result |
|---|---|
| CNBC Indonesia (`/market/rss`, `/rss`) | real RSS 2.0, current (dated today), substantial |
| Detik Finance (`finance.detik.com/rss`) | real RSS 2.0, current, substantial |
| Antara News (`/rss/ekonomi.xml`) | real RSS 2.0, current, substantial -- Indonesia's national news agency |
| Katadata (`/rss`) | real RSS 2.0, current, substantial |
| Kontan (`investasi.kontan.co.id/rss`) | real feed, but genuinely **empty** (`<channel>` with zero `<item>`s) -- excluded, not silently treated as "0 articles found" |
| Bisnis.com (`/rss`, `finansial.bisnis.com/rss`) | HTTP 403 -- blocks automated access, excluded |
| Investor Daily (`investor.id/rss`) | HTTP 404 -- guessed URL wrong, real endpoint not found live, excluded rather than guessed further |
| IDX's own site (`idx.co.id/.../berita/rss`) | HTTP 403 -- same Cloudflare block already documented in `docs/data_sources.md` for IDX's OHLCV endpoints |

Four real, working, current feeds -- `FEED_REGISTRY` below -- meets spec
section 3.6's ">=5 distinct domains" target loosely (4 news domains; a
5th, official-disclosure-tier source would need IDX's own feed, which is
blocked, see above).

**credibility_tier is an editorial judgment call**, not a fabricated or
authoritative rating (spec section 3.6's own tier scale, 1=regulator/
official .. 6=blog/opinion): Antara News (Indonesia's state news agency)
and CNBC Indonesia (major established financial outlet) are tier 2;
Detik Finance and Katadata are tier 3. Documented here so it can be
revisited, not presented as more rigorous than it is.

**Known limitation, stated plainly**: RSS feeds are not searchable by
ticker -- there is no server-side "articles about BBCA" endpoint.
``search()`` (required by the ``NewsProvider`` interface) fetches the
whole feed and does a best-effort ticker-code substring match in
title+description, which will miss articles that only use a company's
*name* ("Bank Central Asia") rather than its ticker code ("BBCA"). No
company-name-alias dictionary is built yet. ``fetch_recent()`` (not part
of the interface) returns the whole feed unfiltered, for the more
realistic "ingest everything, link entities afterward" workflow the
ingestion layer actually uses (it has real company-name data to match
against; the adapter layer deliberately does not touch the database).

**Real false-positive found and fixed while testing entity-linking
against the full real company universe (2026-07-25)**: several real IDX
tickers are also ordinary Indonesian words -- e.g. `EMAS` (PT Merdeka
Gold Resources; "emas" = gold) and `NAIK` (PT Adiarwana Anugerah Abadi;
"naik" = to rise). A case-insensitive match turned a completely unrelated
gold-price headline ("Harga emas dunia naik tipis...", "world gold price
rises slightly") into false entity links for both companies. Fixed by
making ``_ticker_pattern`` **case-sensitive** (uppercase only): Indonesian
financial journalism consistently capitalizes ticker codes when referring
to the stock ("Saham BBCA naik") but writes ordinary words in normal
sentence case ("harga emas naik") -- this asymmetry is a real, load-
bearing signal, not a cosmetic choice. This does not eliminate every
false positive (a headline that happens to fully capitalize a word
coinciding with a ticker would still match), but removes the specific,
common failure mode of ordinary lowercase Indonesian words.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import httpx

from src.data_sources.base import (
    AccessType,
    ProviderUnavailableError,
    SourceDescriptor,
    SourcedValue,
    ValidationStatus,
)
from src.data_sources.news.base import NewsProvider, RawNewsArticle


@dataclasses.dataclass(frozen=True, slots=True)
class FeedConfig:
    provider_name: str
    source_domain: str
    feed_url: str
    media_name: str
    credibility_tier: int


FEED_REGISTRY: list[FeedConfig] = [
    FeedConfig("antara_ekonomi_rss", "antaranews.com", "https://www.antaranews.com/rss/ekonomi.xml", "Antara News", 2),
    FeedConfig("cnbc_indonesia_market_rss", "cnbcindonesia.com", "https://www.cnbcindonesia.com/market/rss", "CNBC Indonesia", 2),
    FeedConfig("detik_finance_rss", "detik.com", "https://finance.detik.com/rss", "Detik Finance", 3),
    FeedConfig("katadata_rss", "katadata.co.id", "https://katadata.co.id/rss", "Katadata", 3),
]

_TICKER_PATTERN_CACHE: dict[str, re.Pattern] = {}


def _ticker_pattern(ticker: str) -> re.Pattern:
    # Case-SENSITIVE (uppercase) on purpose -- see module docstring's
    # "real false-positive found and fixed" note. Several real IDX
    # tickers (EMAS, NAIK, ...) are also ordinary Indonesian words;
    # matching only the capitalized form real journalism uses for ticker
    # codes avoids false-linking on ordinary lowercase usage.
    if ticker not in _TICKER_PATTERN_CACHE:
        _TICKER_PATTERN_CACHE[ticker] = re.compile(rf"\b{re.escape(ticker.upper())}\b")
    return _TICKER_PATTERN_CACHE[ticker]


def _text(el: ET.Element | None) -> str | None:
    return el.text.strip() if el is not None and el.text else None


def _parse_pubdate(raw: str | None) -> dt.datetime | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None


class RSSFeedAdapter(NewsProvider):
    def __init__(self, config: FeedConfig, client: httpx.Client | None = None) -> None:
        self._config = config
        self._client = client or httpx.Client(timeout=20.0, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True)
        self._source = SourceDescriptor(name=config.provider_name, url=config.feed_url, access_type=AccessType.DOCUMENTED_FREE)

    @property
    def provider_name(self) -> str:
        return self._config.provider_name

    @property
    def source_domain(self) -> str:
        return self._config.source_domain

    def _fetch_items(self) -> list[RawNewsArticle]:
        try:
            response = self._client.get(self._config.feed_url)
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"{self.provider_name} request failed: {exc}") from exc
        if response.status_code >= 400:
            raise ProviderUnavailableError(f"{self.provider_name} returned HTTP {response.status_code}")

        try:
            root = ET.fromstring(response.text)
        except ET.ParseError as exc:
            raise ProviderUnavailableError(f"{self.provider_name} returned unparseable XML: {exc}") from exc

        articles = []
        for item in root.findall(".//item"):
            link = _text(item.find("link"))
            title = _text(item.find("title"))
            if not link or not title:
                continue  # a real item needs at minimum a URL and a title -- never fabricate either
            articles.append(
                RawNewsArticle(
                    canonical_url=link,
                    title=title,
                    media_name=self._config.media_name,
                    language="id",
                    summary=_text(item.find("description")),
                    content_snippet=_text(item.find("{http://purl.org/rss/1.0/modules/content/}encoded")),
                    author=_text(item.find("author")) or _text(item.find("{http://purl.org/dc/elements/1.1/}creator")),
                    published_at=_parse_pubdate(_text(item.find("pubDate"))),
                )
            )
        return articles

    def fetch_recent(self, since: dt.datetime, until: dt.datetime) -> SourcedValue[list[RawNewsArticle]]:
        """Whole-feed fetch, date-filtered, no ticker filtering -- see
        module docstring for why this (not ``search``) is what the
        ingestion layer actually uses."""
        now = dt.datetime.now(dt.UTC)
        items = self._fetch_items()
        filtered = [a for a in items if a.published_at is not None and since <= a.published_at <= until]
        return SourcedValue(
            value=filtered,
            source=self._source,
            retrieved_at=now,
            available_at=now,
            period_start=since.date(),
            period_end=until.date(),
            validation_status=ValidationStatus.VALID if filtered else ValidationStatus.INSUFFICIENT,
        )

    def search(self, ticker: str, since: dt.datetime, until: dt.datetime) -> SourcedValue[list[RawNewsArticle]]:
        result = self.fetch_recent(since, until)
        pattern = _ticker_pattern(ticker)
        matched = [a for a in result.value if pattern.search(a.title) or (a.summary and pattern.search(a.summary))]
        for a in matched:
            a.mentioned_tickers = [ticker]
        return SourcedValue(
            value=matched,
            source=result.source,
            retrieved_at=result.retrieved_at,
            available_at=result.available_at,
            period_start=result.period_start,
            period_end=result.period_end,
            validation_status=ValidationStatus.VALID if matched else ValidationStatus.INSUFFICIENT,
        )
