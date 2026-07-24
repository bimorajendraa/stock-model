"""News provider interface (spec §3.6).

Content returned here is untrusted input (spec §2.18-19): downstream code
must never execute instructions found inside title/summary/content_snippet
fields. This interface only fetches; deduplication, sentiment scoring, and
credibility weighting happen in src/features/sentiment (Tahap 3) and
src/ml/sentiment_models (Tahap 4), never inside an adapter.
"""
from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod

from src.data_sources.base import SourcedValue


class RawNewsArticle:
    __slots__ = (
        "author",
        "canonical_url",
        "content_snippet",
        "language",
        "media_name",
        "mentioned_tickers",
        "published_at",
        "summary",
        "title",
    )

    def __init__(
        self,
        canonical_url: str,
        title: str,
        media_name: str,
        language: str,
        summary: str | None = None,
        content_snippet: str | None = None,
        author: str | None = None,
        published_at: dt.datetime | None = None,
        mentioned_tickers: list[str] | None = None,
    ) -> None:
        self.canonical_url = canonical_url
        self.title = title
        self.summary = summary
        self.content_snippet = content_snippet
        self.media_name = media_name
        self.author = author
        self.published_at = published_at
        self.language = language
        self.mentioned_tickers = mentioned_tickers or []


class NewsProvider(ABC):
    """One adapter per domain/API (regulator disclosure feed, a news API,
    an RSS feed, ...). The spec targets >=5 distinct domains per company
    analysis (§3.6) -- that diversity comes from registering multiple
    adapters, not from one adapter returning fake variety."""

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def source_domain(self) -> str: ...

    @abstractmethod
    def search(
        self, ticker: str, since: dt.datetime, until: dt.datetime
    ) -> SourcedValue[list[RawNewsArticle]]: ...
