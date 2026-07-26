"""CLI command implementations for news ingestion (spec section 3.6)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from src.cli.market import _finish_pipeline_run, _start_pipeline_run
from src.config.settings import Settings
from src.data_sources.news.rss import FEED_REGISTRY, RSSFeedAdapter
from src.ingestion.news import ingest_news_from_feed

_DEFAULT_LOOKBACK_DAYS = 3  # RSS feeds only ever carry recent items -- no point asking for more


def cmd_news_sync(session: Session, settings: Settings, lookback_days: int = _DEFAULT_LOOKBACK_DAYS) -> int:
    run = _start_pipeline_run(session, "news_sync")
    until = dt.datetime.now(dt.UTC)
    since = until - dt.timedelta(days=lookback_days)

    total_written = 0
    total_skipped = 0

    for config in FEED_REGISTRY:
        adapter = RSSFeedAdapter(config)
        outcome = ingest_news_from_feed(session, adapter, config.credibility_tier, since, until)
        session.commit()
        if outcome.skipped_reason:
            total_skipped += 1
            print(f"{config.provider_name}: SKIPPED ({outcome.skipped_reason})")
            continue
        print(
            f"{config.provider_name}: fetched={outcome.articles_fetched} "
            f"written={outcome.articles_written} entity_links={outcome.entity_links_written}"
        )
        total_written += outcome.articles_written

    _finish_pipeline_run(session, run, total_written, total_skipped, None)
    print(f"\nNews-sync summary: {len(FEED_REGISTRY)} feeds, {total_written} articles written, {total_skipped} skipped")
    return 0
