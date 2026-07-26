"""News ingestion: RSS feed -> ``news_articles`` + ``news_entities``
(spec section 3.6).

Real, deduplicated (``canonical_url`` has a real DB unique constraint --
genuine ``ON CONFLICT`` upsert for ``news_articles``, not clear-then-
rewrite), entity-linked via ticker-code matching against every real
company (spec section 2.18-19: article content is untrusted input, never
executed as an instruction -- it is only ever matched against, never
interpreted). ``news_entities`` has no unique constraint of its own
(Tahap 1 schema) -- idempotency there is clear-then-rewrite per article,
same pattern as ``technical_features``/``financial_ratios`` elsewhere in
this project.

**Known, honestly-stated limitations**:
- Entity linking matches only the raw ticker code as a whole word in the
  title/summary (e.g. "BBCA") -- it will miss articles that only use a
  company's *name* ("Bank Central Asia"). No company-name-alias
  dictionary is built yet.
- Semantic/embedding-based deduplication (``NewsArticle.title_embedding``,
  spec's cross-source-confirmation intent) is NOT implemented -- no
  embedding model is configured. ``is_duplicate``/``duplicate_of_id``/
  ``cross_source_confirmed`` all stay at their model defaults
  (``False``/``None``) rather than a fabricated guess. The real, natural
  dedup that IS enforced is exact-URL (``canonical_url`` uniqueness).
"""
from __future__ import annotations

import dataclasses
import datetime as dt

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.data_sources.base import ProviderUnavailableError, SourceDescriptor
from src.data_sources.news.base import NewsProvider
from src.data_sources.news.rss import _ticker_pattern
from src.database.models.company import Company
from src.database.models.mixins import QualityStatus
from src.database.models.news import NewsArticle, NewsEntity
from src.database.models.ops import DataSourceRegistry
from src.ingestion.resilience import with_retry


@dataclasses.dataclass
class NewsIngestOutcome:
    provider: str
    articles_fetched: int = 0
    articles_written: int = 0
    entity_links_written: int = 0
    skipped_reason: str | None = None


def _get_or_create_source(session: Session, descriptor: SourceDescriptor, category: str) -> DataSourceRegistry:
    source = session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == descriptor.name))
    if source is not None:
        return source
    source = DataSourceRegistry(
        name=descriptor.name,
        category=category,
        access_type=descriptor.access_type.value,
        base_url=descriptor.url,
        is_active=True,
    )
    session.add(source)
    session.flush()
    return source


def ingest_news_from_feed(
    session: Session,
    provider: NewsProvider,
    credibility_tier: int,
    since: dt.datetime,
    until: dt.datetime,
    max_retries: int = 4,
) -> NewsIngestOutcome:
    outcome = NewsIngestOutcome(provider=provider.provider_name)

    try:
        fetch = with_retry(max_retries)(provider.fetch_recent)
        result = fetch(since, until)
    except ProviderUnavailableError as exc:
        outcome.skipped_reason = f"provider unavailable: {exc}"
        return outcome

    if not result.is_usable():
        outcome.skipped_reason = f"provider returned no usable data (status={result.validation_status.value})"
        return outcome

    articles = result.value
    outcome.articles_fetched = len(articles)
    if not articles:
        return outcome

    source = _get_or_create_source(session, result.source, category="news")
    now = dt.datetime.now(dt.UTC)

    # Ticker-code entity matching needs every real company's ticker --
    # loaded once per call, not once per article.
    companies = list(session.scalars(select(Company)))

    for article in articles:
        available_at = article.published_at or now
        stmt = insert(NewsArticle).values(
            canonical_url=article.canonical_url,
            title=article.title,
            summary=article.summary,
            content_snippet=article.content_snippet,
            media_name=article.media_name,
            author=article.author,
            published_at=article.published_at,
            language=article.language,
            credibility_tier=credibility_tier,
            is_duplicate=False,
            cross_source_confirmed=False,
            source_id=source.id,
            retrieved_at=now,
            available_at=available_at,
            currency="IDR",
            unit="unit",
            is_restated=False,
            quality_status=QualityStatus.VALID,
        )
        # title/summary can legitimately change if an outlet edits a
        # published article -- update in place on a re-fetch, never
        # duplicate (canonical_url is the real natural key).
        stmt = stmt.on_conflict_do_update(
            index_elements=["canonical_url"],
            set_={"title": stmt.excluded.title, "summary": stmt.excluded.summary, "retrieved_at": stmt.excluded.retrieved_at},
        ).returning(NewsArticle.id)
        article_id = session.execute(stmt).scalar_one()
        outcome.articles_written += 1

        # No unique constraint on news_entities -- clear this article's
        # links first so re-ingesting it (e.g. tomorrow's run refetching
        # today's still-recent articles) doesn't accumulate duplicates.
        session.query(NewsEntity).filter(NewsEntity.article_id == article_id).delete()

        haystack = f"{article.title} {article.summary or ''}"
        matched_company_ids = [c.id for c in companies if _ticker_pattern(c.ticker).search(haystack)]
        if matched_company_ids:
            session.execute(
                insert(NewsEntity),
                [{"article_id": article_id, "company_id": company_id} for company_id in matched_company_ids],
            )
            outcome.entity_links_written += len(matched_company_ids)

    return outcome
