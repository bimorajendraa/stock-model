"""``news_articles`` + ``news_entities`` -> ``news_sentiment`` (spec
section 3.6), scored by the pretrained classifier in ``model.py``.

One ``news_sentiment`` row per (article, linked company) pair. The
classifier scores the whole article's title+summary text, not a
per-company/aspect-based sentiment -- every company mentioned in one
article currently gets the *same* score. A real, disclosed simplification,
not aspect-based sentiment.

Structural limitation inherited from the existing schema, not introduced
here: ``news_sentiment.company_id`` is a non-nullable FK, so an article
with **no** ticker entity link (most articles -- see ``docs/news.md``'s
real entity-link counts) gets **no** sentiment row at all, even though it
may still carry real market-wide sentiment. Not worked around by inventing
a NULL-company convention that isn't in the schema.

``news_sentiment`` has no unique constraint on (article_id, company_id) --
by design (see ``news.py``'s model docstring: a re-scored article must
never silently overwrite an older score). Idempotency here is therefore
"skip pairs already scored by this exact ``model_version``", not upsert --
scoring the same articles again with a *different* model_version adds new
rows rather than replacing anything.
"""
from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models.company import Company
from src.database.models.news import NewsArticle, NewsEntity, NewsSentiment
from src.features.sentiment.finance_rules import classify_financial_event
from src.features.sentiment.model import SentimentModelResult, derive_score_and_label, score_financial_text

ScorerFn = Callable[[str], SentimentModelResult]


def _company_context(text: str, ticker: str, company_name: str, matched_text: str | None) -> str:
    """Prefer sentences about this company; fall back to the whole article snippet."""
    needles = [ticker.casefold(), company_name.casefold()]
    if matched_text:
        needles.append(matched_text.casefold())
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    matched = [sentence for sentence in sentences if any(needle in sentence.casefold() for needle in needles)]
    return " ".join(matched) if matched else text


@dataclasses.dataclass
class SentimentPipelineOutcome:
    articles_considered: int = 0
    pairs_scored: int = 0
    pairs_skipped_already_scored: int = 0


def compute_sentiment_for_unscored_pairs(
    session: Session,
    model_version: str,
    scorer: ScorerFn = score_financial_text,
    limit: int | None = None,
    company_ids: list[int] | None = None,
) -> SentimentPipelineOutcome:
    outcome = SentimentPipelineOutcome()

    already_scored_query = select(NewsSentiment.article_id, NewsSentiment.company_id).where(
        NewsSentiment.model_version == model_version
    )
    if company_ids is not None:
        already_scored_query = already_scored_query.where(NewsSentiment.company_id.in_(company_ids))
    already_scored = set(session.execute(already_scored_query).all())

    query = (
        select(
            NewsArticle.id,
            NewsArticle.title,
            NewsArticle.summary,
            NewsArticle.content_snippet,
            NewsEntity.company_id,
            NewsEntity.matched_text,
            Company.ticker,
            Company.company_name,
        )
        .join(NewsEntity, NewsEntity.article_id == NewsArticle.id)
        .join(Company, Company.id == NewsEntity.company_id)
        .order_by(NewsArticle.id)
    )
    if company_ids is not None:
        query = query.where(NewsEntity.company_id.in_(company_ids))
    rows = session.execute(query).all()

    seen_articles: set[int] = set()
    to_insert: list[NewsSentiment] = []
    for article_id, title, summary, content_snippet, company_id, matched_text, ticker, company_name in rows:
        seen_articles.add(article_id)
        if (article_id, company_id) in already_scored:
            outcome.pairs_skipped_already_scored += 1
            continue
        if limit is not None and outcome.pairs_scored >= limit:
            continue

        text = f"{title}. {summary or ''} {content_snippet or ''}".strip()
        context = _company_context(text, ticker, company_name, matched_text)
        result = scorer(context)
        score, label = derive_score_and_label(result)
        event = classify_financial_event(context)
        to_insert.append(
            NewsSentiment(
                article_id=article_id,
                company_id=company_id,
                sentiment_label=label,
                sentiment_score=score,
                event_category=event.category,
                severity=event.severity,
                impact_horizon=event.impact_horizon,
                model_version=model_version,
            )
        )
        outcome.pairs_scored += 1

    outcome.articles_considered = len(seen_articles)
    session.add_all(to_insert)
    return outcome
