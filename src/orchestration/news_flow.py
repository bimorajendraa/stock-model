"""Prefect flow for daily news ingestion (spec section 5/23,
ADR-0002's chosen orchestrator).

**Honest status, corrected after actually running this** (2026-07-25):
`docker-compose.yml` has no Prefect service and the configured
`PREFECT_API_URL` (`.env`: `http://localhost:4200/api`) is not reachable
-- running this flow with that env var set fails outright (`RuntimeError:
Failed to reach API`). ADR-0002's claim that "Prefect flows run natively
without a server" is **not quite right for Prefect 3.x** in practice:
with `PREFECT_API_URL` unset, Prefect instead spins up its own
**ephemeral local API server** automatically (confirmed live: "Stopping
temporary server on http://127.0.0.1:8395" in the run log) -- there's
still a server involved, just a disposable one Prefect manages itself,
not a persistent deployment. Running this flow for real also surfaced a
second real bug (see `ingest_one_feed`'s docstring).

A third real observation from actually running this: even after the
cache-policy fix below, the ephemeral-server path logs harmless-but-noisy
``RuntimeError: Cannot put items in a stopped service instance`` traces
from Prefect's own event-emission worker on a fast-completing flow (this
one finishes in ~2s) -- the flow still reaches ``Completed`` and every
article is still written correctly (verified: same 231-article, 0-skipped
result as the plain CLI path), but the log noise is a real, observed
rough edge of Prefect's ephemeral mode, not something this project's code
causes or can fix.

The normal daily mechanism is now the Docker-supervised
``src.orchestration.news_scheduler`` service documented in `docs/news.md`.
It uses PostgreSQL for both an advisory lock and health evidence, so it does
not depend on Prefect's ephemeral server or an interactive Windows logon.
This flow exists as real, verified-runnable code so the same ingestion
logic can be adopted into a real Prefect deployment later (spec/ADR-0002's
longer-term direction) without being rewritten -- run it manually with
``PREFECT_API_URL= python -m src.orchestration.news_flow`` (cleared, not
the `.env` default) to reproduce the ephemeral-server path used above.
"""
from __future__ import annotations

import datetime as dt

from prefect import flow, get_run_logger, task
from prefect.cache_policies import NO_CACHE
from sqlalchemy.orm import Session

from src.cli.market import _finish_pipeline_run, _start_pipeline_run
from src.cli.news import enabled_feed_configs
from src.config.settings import get_settings
from src.data_sources.news.rss import FeedConfig, RSSFeedAdapter
from src.database.session import make_engine
from src.ingestion.news import NewsIngestOutcome, ingest_news_from_feed

_DEFAULT_LOOKBACK_DAYS = 3


@task(name="ingest_one_news_feed", retries=2, retry_delay_seconds=30, cache_policy=NO_CACHE)
def ingest_one_feed(session: Session, config: FeedConfig, since: dt.datetime, until: dt.datetime) -> NewsIngestOutcome:
    """``cache_policy=NO_CACHE`` is required, not cosmetic: a real bug hit
    running this live -- Prefect's default cache-key computation tries to
    serialize every task argument, and a SQLAlchemy ``Session`` is neither
    JSON- nor pickle-serializable ("cannot pickle 'weakref.ReferenceType'
    object"). Without this, the task still completes (Prefect logs the
    serialization failure and skips caching for that call rather than
    crashing the flow), but it prints a real ERROR-level trace on every
    run -- suppressed properly here rather than ignored."""
    adapter = RSSFeedAdapter(config)
    outcome = ingest_news_from_feed(session, adapter, config.credibility_tier, since, until)
    session.commit()
    return outcome


@flow(name="daily_news_sync")
def daily_news_sync_flow(lookback_days: int = _DEFAULT_LOOKBACK_DAYS) -> None:
    logger = get_run_logger()
    until = dt.datetime.now(dt.UTC)
    since = until - dt.timedelta(days=lookback_days)

    engine = make_engine()
    feed_configs = enabled_feed_configs(get_settings())
    with Session(engine) as session:
        run = _start_pipeline_run(session, "news_sync")
        total_written = 0
        total_skipped = 0

        for config in feed_configs:
            outcome = ingest_one_feed(session, config, since, until)
            if outcome.skipped_reason:
                total_skipped += 1
                logger.warning(f"{config.provider_name}: SKIPPED ({outcome.skipped_reason})")
                continue
            logger.info(
                f"{config.provider_name}: fetched={outcome.articles_fetched} "
                f"written={outcome.articles_written} entity_links={outcome.entity_links_written}"
            )
            total_written += outcome.articles_written

        _finish_pipeline_run(session, run, total_written, total_skipped, None)
        logger.info(f"daily_news_sync: {len(feed_configs)} feeds, {total_written} articles written, {total_skipped} skipped")


if __name__ == "__main__":
    daily_news_sync_flow()
