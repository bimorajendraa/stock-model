"""Integration tests for news ingestion -- requires a live database. Uses
a fake provider (distinct source name from any real feed) and a
disposable fixture company (never a real ticker), so cleanup can't
collide with real production data (same lesson as
``test_ingestion_fundamentals.py``'s module docstring).
"""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.data_sources.base import AccessType, SourceDescriptor, SourcedValue, ValidationStatus
from src.data_sources.news.base import NewsProvider, RawNewsArticle
from src.database.models.company import Company
from src.database.models.news import NewsArticle, NewsEntity
from src.database.models.ops import DataSourceRegistry
from src.database.session import make_engine
from src.ingestion.news import ingest_news_from_feed

pytestmark = pytest.mark.integration

_FAKE_SOURCE_NAME = "fake_news_test_source"
_FIXTURE_TICKER = "ZZZNEWS"


@pytest.fixture()
def db_session():
    engine = make_engine("postgresql+psycopg://idx:idx@localhost:5433/idx_intelligence")
    with Session(engine) as session:
        yield session
        session.rollback()


class _FakeNewsProvider(NewsProvider):
    def __init__(self, articles: list[RawNewsArticle]) -> None:
        self._articles = articles
        self._source = SourceDescriptor(name=_FAKE_SOURCE_NAME, url="https://example.invalid", access_type=AccessType.DOCUMENTED_FREE)

    @property
    def provider_name(self) -> str:
        return "fake_news"

    @property
    def source_domain(self) -> str:
        return "example.invalid"

    def search(self, ticker, since, until):
        raise NotImplementedError

    def fetch_recent(self, since: dt.datetime, until: dt.datetime) -> SourcedValue[list[RawNewsArticle]]:
        now = dt.datetime.now(dt.UTC)
        return SourcedValue(
            value=self._articles,
            source=self._source,
            retrieved_at=now,
            available_at=now,
            period_start=since.date(),
            period_end=until.date(),
            validation_status=ValidationStatus.VALID if self._articles else ValidationStatus.INSUFFICIENT,
        )


@pytest.fixture()
def fixture_company(db_session):
    company = db_session.scalar(select(Company).where(Company.ticker == _FIXTURE_TICKER))
    if company is None:
        company = Company(ticker=_FIXTURE_TICKER, company_name="Test Fixture News Co")
        db_session.add(company)
        db_session.commit()
    yield company


@pytest.fixture(autouse=True)
def _cleanup(db_session, fixture_company):
    yield
    source = db_session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == _FAKE_SOURCE_NAME))
    if source is not None:
        article_ids = [
            a.id for a in db_session.scalars(select(NewsArticle).where(NewsArticle.source_id == source.id)).all()
        ]
        if article_ids:
            db_session.query(NewsEntity).filter(NewsEntity.article_id.in_(article_ids)).delete(synchronize_session=False)
            db_session.query(NewsArticle).filter(NewsArticle.id.in_(article_ids)).delete(synchronize_session=False)
        db_session.query(DataSourceRegistry).filter(DataSourceRegistry.id == source.id).delete()
    db_session.query(Company).filter(Company.ticker == _FIXTURE_TICKER).delete()
    db_session.commit()


def _article(url: str, title: str, summary: str | None = None, published_at: dt.datetime | None = None) -> RawNewsArticle:
    return RawNewsArticle(
        canonical_url=url,
        title=title,
        media_name="Test Media",
        language="id",
        summary=summary,
        published_at=published_at or dt.datetime.now(dt.UTC),
    )


def test_ingest_news_writes_articles_and_links_ticker_entity(db_session, fixture_company):
    provider = _FakeNewsProvider(
        [_article("https://example.invalid/a1", f"Saham {_FIXTURE_TICKER} melesat hari ini")]
    )
    outcome = ingest_news_from_feed(
        db_session, provider, credibility_tier=3,
        since=dt.datetime.now(dt.UTC) - dt.timedelta(days=1), until=dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
    )
    db_session.commit()

    assert outcome.skipped_reason is None
    assert outcome.articles_written == 1
    assert outcome.entity_links_written == 1

    article = db_session.scalar(select(NewsArticle).where(NewsArticle.canonical_url == "https://example.invalid/a1"))
    assert article is not None
    assert article.credibility_tier == 3

    link = db_session.scalar(
        select(NewsEntity).where(NewsEntity.article_id == article.id, NewsEntity.company_id == fixture_company.id)
    )
    assert link is not None


def test_ingest_news_no_ticker_mention_gets_no_entity_link(db_session, fixture_company):
    provider = _FakeNewsProvider([_article("https://example.invalid/a2", "Harga emas dunia naik tipis hari ini")])
    outcome = ingest_news_from_feed(
        db_session, provider, credibility_tier=3,
        since=dt.datetime.now(dt.UTC) - dt.timedelta(days=1), until=dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
    )
    db_session.commit()

    assert outcome.articles_written == 1
    assert outcome.entity_links_written == 0


def test_ingest_news_is_idempotent_on_url_no_duplicate_articles(db_session, fixture_company):
    provider = _FakeNewsProvider([_article("https://example.invalid/a3", f"Berita {_FIXTURE_TICKER} pertama")])
    ingest_news_from_feed(
        db_session, provider, credibility_tier=3,
        since=dt.datetime.now(dt.UTC) - dt.timedelta(days=1), until=dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
    )
    db_session.commit()

    provider_v2 = _FakeNewsProvider([_article("https://example.invalid/a3", f"Berita {_FIXTURE_TICKER} direvisi")])
    ingest_news_from_feed(
        db_session, provider_v2, credibility_tier=3,
        since=dt.datetime.now(dt.UTC) - dt.timedelta(days=1), until=dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
    )
    db_session.commit()

    rows = db_session.scalars(select(NewsArticle).where(NewsArticle.canonical_url == "https://example.invalid/a3")).all()
    assert len(rows) == 1  # ON CONFLICT upsert, not a duplicate row
    assert rows[0].title == f"Berita {_FIXTURE_TICKER} direvisi"  # updated in place

    links = db_session.scalars(select(NewsEntity).where(NewsEntity.article_id == rows[0].id)).all()
    assert len(links) == 1  # entity links not duplicated across the re-ingest either


def test_ingest_news_no_usable_articles_is_skipped(db_session):
    provider = _FakeNewsProvider([])
    outcome = ingest_news_from_feed(
        db_session, provider, credibility_tier=3,
        since=dt.datetime.now(dt.UTC) - dt.timedelta(days=1), until=dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
    )
    assert outcome.skipped_reason is not None
    assert outcome.articles_written == 0
