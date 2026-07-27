"""Durable daily news scheduler service with DB-backed health checks.

This process is intentionally small: Docker/OS supervises the process,
PostgreSQL records every actual ``news_sync`` run, and a PostgreSQL
advisory lock prevents duplicate scheduler replicas from running the job
at the same time.  It does not depend on an ephemeral Prefect server.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import time
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.cli.news import cmd_news_sync
from src.config.settings import Settings, get_settings
from src.database.models.ops import PipelineRun
from src.database.session import make_engine

logger = logging.getLogger(__name__)
_ADVISORY_LOCK_ID = 627_202_607


def next_scheduled_run(
    now: dt.datetime,
    timezone: str,
    hour: int,
    minute: int,
) -> dt.datetime:
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("news schedule hour/minute is outside the valid range")
    zone = ZoneInfo(timezone)
    local_now = now.astimezone(zone)
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local_now:
        candidate += dt.timedelta(days=1)
    return candidate


def run_once(settings: Settings) -> int:
    engine = make_engine(settings.database_url)
    # Bind the ORM Session to one explicit physical connection: PostgreSQL
    # session-level advisory locks belong to that connection and must be
    # released on the same one even though cmd_news_sync commits per feed.
    with engine.connect() as connection:
        acquired = bool(connection.scalar(text(f"select pg_try_advisory_lock({_ADVISORY_LOCK_ID})")))
        if not acquired:
            logger.info("news scheduler skipped: another replica holds the advisory lock")
            return 0
        try:
            with Session(bind=connection) as session:
                return cmd_news_sync(session, settings)
        finally:
            connection.execute(text(f"select pg_advisory_unlock({_ADVISORY_LOCK_ID})"))
            connection.commit()


def healthcheck(settings: Settings, max_age_hours: int = 36) -> int:
    engine = make_engine(settings.database_url)
    # PipelineRun timestamps predate the timezone-aware fact-table policy
    # and are stored as PostgreSQL TIMESTAMP WITHOUT TIME ZONE. Treat them
    # consistently as naive UTC at this boundary.
    now_utc_naive = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    cutoff = now_utc_naive - dt.timedelta(hours=max_age_hours)
    with Session(engine) as session:
        latest = session.scalar(
            select(PipelineRun)
            .where(PipelineRun.pipeline_name == "news_sync")
            .order_by(PipelineRun.started_at.desc())
        )
        stale_running = session.scalar(
            select(PipelineRun.id).where(
                PipelineRun.pipeline_name == "news_sync",
                PipelineRun.status == "running",
                PipelineRun.started_at < now_utc_naive - dt.timedelta(hours=2),
            )
        )
    if stale_running is not None:
        logger.error("news scheduler unhealthy: stale running job")
        return 1
    if latest is None or latest.completed_at is None or latest.completed_at < cutoff:
        logger.error("news scheduler unhealthy: no completed news sync within %s hours", max_age_hours)
        return 1
    if latest.status not in {"succeeded", "partial"}:
        logger.error("news scheduler unhealthy: latest status=%s", latest.status)
        return 1
    return 0


def serve(settings: Settings) -> None:
    # Run on startup so a new deployment proves provider + DB behavior
    # immediately, then settle into the configured local-time schedule.
    run_once(settings)
    while True:
        now = dt.datetime.now(dt.UTC)
        next_run = next_scheduled_run(
            now,
            settings.timezone,
            settings.news_schedule_hour,
            settings.news_schedule_minute,
        )
        logger.info("next news sync at %s", next_run.isoformat())
        while dt.datetime.now(dt.UTC) < next_run.astimezone(dt.UTC):
            remaining = (next_run.astimezone(dt.UTC) - dt.datetime.now(dt.UTC)).total_seconds()
            time.sleep(max(1.0, min(60.0, remaining)))
        run_once(settings)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    if args.healthcheck:
        return healthcheck(settings)
    if args.once:
        return run_once(settings)
    serve(settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
