"""News, entity links, sentiment, and reputation/red-flag events (spec §3.6, §22).

News content is untrusted input (spec §2.18-19): nothing in ``news_articles``
is ever treated as an instruction, and sentiment/classification always lands
in a separate row (``news_sentiment``) tied to a model version -- so a
re-scored article doesn't silently overwrite the original text.
"""
from __future__ import annotations

import datetime as dt

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base
from src.database.models.mixins import SourceLineageMixin, TimestampMixin

EMBEDDING_DIM = 768  # must match the sentence-embedding model used for dedup (Tahap 3)


class NewsArticle(Base, TimestampMixin, SourceLineageMixin):
    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)

    media_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    author: Mapped[str | None] = mapped_column(String(256), nullable=True)
    published_at: Mapped[dt.datetime | None] = mapped_column(nullable=True, index=True)
    language: Mapped[str] = mapped_column(String(8), nullable=False)

    credibility_tier: Mapped[int] = mapped_column(nullable=False)
    # 1=regulator/official disclosure .. 6=blog/opinion, per spec §3.6 weighting

    is_duplicate: Mapped[bool] = mapped_column(nullable=False, default=False)
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("news_articles.id"), nullable=True)
    cross_source_confirmed: Mapped[bool] = mapped_column(nullable=False, default=False)

    title_embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)


class NewsEntity(Base, TimestampMixin):
    """Many-to-many: which companies/tickers an article mentions."""

    __tablename__ = "news_entities"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("news_articles.id"), nullable=False, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    relevance_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    match_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    matched_text: Mapped[str | None] = mapped_column(String(256), nullable=True)


class NewsSentiment(Base, TimestampMixin):
    """Output of the sentiment/event-classification model for one article
    x company pair. Never computed by an LLM narrator (spec §2.15/§12)."""

    __tablename__ = "news_sentiment"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("news_articles.id"), nullable=False, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)

    sentiment_label: Mapped[str] = mapped_column(String(24), nullable=False)
    # sangat_negatif | negatif | netral | positif | sangat_positif
    sentiment_score: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)

    event_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)  # low | medium | high | critical
    novelty: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_confirmed: Mapped[bool] = mapped_column(nullable=False, default=False)
    impact_horizon: Mapped[str | None] = mapped_column(String(16), nullable=True)  # temporary | structural

    model_version: Mapped[str] = mapped_column(String(64), nullable=False)


class ReputationEvent(Base, TimestampMixin, SourceLineageMixin):
    """Material events feeding the Red Flag Engine (spec §22): fraud,
    lawsuits, regulatory sanctions, going-concern, etc."""

    __tablename__ = "reputation_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    event_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")  # active | resolved
    potential_impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    related_article_id: Mapped[int | None] = mapped_column(ForeignKey("news_articles.id"), nullable=True)
