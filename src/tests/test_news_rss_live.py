"""Live-network tests for the RSS adapter -- hits the real feeds (no
mock), consistent with how every other external call in this project is
verified. No database needed, but marked ``integration`` anyway.
"""
from __future__ import annotations

import datetime as dt

import pytest

from src.data_sources.base import ValidationStatus
from src.data_sources.news.rss import FEED_REGISTRY, RSSFeedAdapter

pytestmark = pytest.mark.integration


def test_feed_registry_has_the_expected_real_feeds():
    names = {c.provider_name for c in FEED_REGISTRY}
    assert names == {"antara_ekonomi_rss", "cnbc_indonesia_market_rss", "detik_finance_rss", "katadata_rss"}


def test_every_registered_feed_returns_real_recent_articles():
    until = dt.datetime.now(dt.UTC)
    since = until - dt.timedelta(days=7)
    for config in FEED_REGISTRY:
        adapter = RSSFeedAdapter(config)
        result = adapter.fetch_recent(since, until)
        assert result.validation_status == ValidationStatus.VALID, f"{config.provider_name} returned no articles"
        assert result.value
        article = result.value[0]
        assert article.canonical_url.startswith("http")
        assert article.title
        assert article.media_name == config.media_name
        assert article.published_at is not None
        assert since <= article.published_at <= until
