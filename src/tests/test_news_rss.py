"""Tests for the RSS news adapter. Parsing tests use ``respx`` against a
fixture RSS payload shaped exactly like the real CNBC Indonesia response
fetched live on 2026-07-25 (same "response shapes taken directly"
convention as ``test_market_adapters.py``) -- no live network needed for
these, but the shape itself isn't invented.
"""
from __future__ import annotations

import datetime as dt

import httpx
import pytest
import respx

from src.data_sources.base import ProviderUnavailableError, ValidationStatus
from src.data_sources.news.rss import FeedConfig, RSSFeedAdapter, _ticker_pattern

# Real shape, from CNBC Indonesia's /market/rss, fetched live 2026-07-25.
_SAMPLE_FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:content="http://purl.org/rss/1.0/modules/content/">
\t<channel>
\t\t<title>Market - CNBC Indonesia</title>
\t\t<link>https://www.cnbcindonesia.com/market</link>
\t\t<item>
\t\t\t<guid>https://www.cnbcindonesia.com/market/20260725181957-17-753808/some-article</guid>
\t\t\t<pubDate>Sat, 25 Jul 2026 21:30:57 +0700</pubDate>
\t\t\t<title><![CDATA[Saham BBCA Melesat Usai Rilis Laporan Keuangan]]></title>
\t\t\t<description><![CDATA[Analis menilai kinerja BBCA solid di kuartal ini.]]></description>
\t\t\t<content:encoded><![CDATA[Analis menilai kinerja BBCA solid di kuartal ini, dengan pertumbuhan laba dua digit.]]></content:encoded>
\t\t\t<link>https://www.cnbcindonesia.com/market/20260725181957-17-753808/some-article</link>
\t\t</item>
\t\t<item>
\t\t\t<guid>https://www.cnbcindonesia.com/market/20260725174622-17-753806/other-article</guid>
\t\t\t<pubDate>Sat, 25 Jul 2026 20:15:22 +0700</pubDate>
\t\t\t<title><![CDATA[Harga Emas Dunia Naik Tipis]]></title>
\t\t\t<description><![CDATA[Harga emas dunia bergerak naik tipis di tengah sentimen pasar.]]></description>
\t\t\t<link>https://www.cnbcindonesia.com/market/20260725174622-17-753806/other-article</link>
\t\t</item>
\t\t<item>
\t\t\t<guid>https://www.cnbcindonesia.com/market/old-article</guid>
\t\t\t<pubDate>Mon, 01 Jan 2024 09:00:00 +0700</pubDate>
\t\t\t<title><![CDATA[Artikel Lama Tahun 2024]]></title>
\t\t\t<link>https://www.cnbcindonesia.com/market/old-article</link>
\t\t</item>
\t</channel>
</rss>
"""

_CONFIG = FeedConfig("test_feed", "example.com", "https://example.com/rss", "Test Feed", 3)


def test_ticker_pattern_matches_whole_word_only():
    pattern = _ticker_pattern("BBCA")
    assert pattern.search("Saham BBCA melesat")
    assert not pattern.search("ABBCAX tidak relevan")  # not a whole-word match


def test_ticker_pattern_is_case_sensitive_to_avoid_dictionary_word_false_positives():
    # Real bug this project hit live: EMAS and NAIK are both real IDX
    # tickers AND ordinary Indonesian words ("emas"=gold, "naik"=rise).
    # Matching must require the capitalized form real journalism uses
    # for ticker codes, not ordinary lowercase sentence usage.
    emas_pattern = _ticker_pattern("EMAS")
    naik_pattern = _ticker_pattern("NAIK")
    assert not emas_pattern.search("Harga emas dunia naik tipis hari ini")
    assert not naik_pattern.search("Harga emas dunia naik tipis hari ini")
    assert emas_pattern.search("Saham EMAS naik tajam pekan ini")  # real ticker mention still matches


@respx.mock
def test_fetch_recent_parses_real_shaped_feed_and_filters_by_date():
    respx.get("https://example.com/rss").mock(return_value=httpx.Response(200, text=_SAMPLE_FEED_XML))
    adapter = RSSFeedAdapter(_CONFIG)

    since = dt.datetime(2026, 7, 20, tzinfo=dt.UTC)
    until = dt.datetime(2026, 7, 26, tzinfo=dt.UTC)
    result = adapter.fetch_recent(since, until)

    assert result.validation_status == ValidationStatus.VALID
    # 2 of the 3 real items fall in range -- the 2024 one must be excluded
    assert len(result.value) == 2
    titles = {a.title for a in result.value}
    assert "Saham BBCA Melesat Usai Rilis Laporan Keuangan" in titles
    assert "Artikel Lama Tahun 2024" not in titles


@respx.mock
def test_fetch_recent_preserves_real_field_values():
    respx.get("https://example.com/rss").mock(return_value=httpx.Response(200, text=_SAMPLE_FEED_XML))
    adapter = RSSFeedAdapter(_CONFIG)
    result = adapter.fetch_recent(dt.datetime(2026, 7, 20, tzinfo=dt.UTC), dt.datetime(2026, 7, 26, tzinfo=dt.UTC))

    bbca_article = next(a for a in result.value if "BBCA" in a.title)
    assert bbca_article.canonical_url == "https://www.cnbcindonesia.com/market/20260725181957-17-753808/some-article"
    assert bbca_article.media_name == "Test Feed"
    assert bbca_article.summary == "Analis menilai kinerja BBCA solid di kuartal ini."
    assert bbca_article.published_at == dt.datetime(2026, 7, 25, 21, 30, 57, tzinfo=dt.timezone(dt.timedelta(hours=7)))


@respx.mock
def test_search_filters_by_ticker_code():
    respx.get("https://example.com/rss").mock(return_value=httpx.Response(200, text=_SAMPLE_FEED_XML))
    adapter = RSSFeedAdapter(_CONFIG)
    result = adapter.search("BBCA", dt.datetime(2026, 7, 20, tzinfo=dt.UTC), dt.datetime(2026, 7, 26, tzinfo=dt.UTC))

    assert len(result.value) == 1
    assert "BBCA" in result.value[0].title
    assert result.value[0].mentioned_tickers == ["BBCA"]


@respx.mock
def test_fetch_recent_empty_feed_is_insufficient():
    empty_xml = '<?xml version="1.0"?><rss version="2.0"><channel><title>Empty</title></channel></rss>'
    respx.get("https://example.com/rss").mock(return_value=httpx.Response(200, text=empty_xml))
    adapter = RSSFeedAdapter(_CONFIG)
    result = adapter.fetch_recent(dt.datetime(2026, 7, 20, tzinfo=dt.UTC), dt.datetime(2026, 7, 26, tzinfo=dt.UTC))
    assert result.validation_status == ValidationStatus.INSUFFICIENT
    assert result.value == []


@respx.mock
def test_fetch_recent_http_error_raises_provider_unavailable():
    respx.get("https://example.com/rss").mock(return_value=httpx.Response(403))
    adapter = RSSFeedAdapter(_CONFIG)
    with pytest.raises(ProviderUnavailableError):
        adapter.fetch_recent(dt.datetime(2026, 7, 20, tzinfo=dt.UTC), dt.datetime(2026, 7, 26, tzinfo=dt.UTC))


@respx.mock
def test_fetch_recent_unparseable_xml_raises_provider_unavailable():
    respx.get("https://example.com/rss").mock(return_value=httpx.Response(200, text="not xml at all <<<"))
    adapter = RSSFeedAdapter(_CONFIG)
    with pytest.raises(ProviderUnavailableError):
        adapter.fetch_recent(dt.datetime(2026, 7, 20, tzinfo=dt.UTC), dt.datetime(2026, 7, 26, tzinfo=dt.UTC))
