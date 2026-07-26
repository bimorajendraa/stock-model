"""Integration tests for the news_sentiment pipeline -- requires a live
database. Uses a fake scorer function (injected via the ``scorer``
parameter) so this never loads the real ~500MB model; the real model is
covered separately by ``test_sentiment_model_live.py``. Fixture company
and articles are disposable (never real tickers/URLs), same pattern as
``test_ingestion_news.py``.
"""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models.company import Company
from src.database.models.mixins import QualityStatus
from src.database.models.news import NewsArticle, NewsEntity, NewsSentiment
from src.database.models.ops import DataSourceRegistry
from src.database.session import make_engine
from src.features.sentiment.model import SentimentModelResult
from src.features.sentiment.pipeline import compute_sentiment_for_unscored_pairs

pytestmark = pytest.mark.integration

_FAKE_SOURCE_NAME = "fake_sentiment_test_source"
_FIXTURE_TICKER = "ZZZSENT"
_MODEL_VERSION = "fake-test-model-v1"


@pytest.fixture()
def db_session():
    engine = make_engine("postgresql+psycopg://idx:idx@localhost:5433/idx_intelligence")
    with Session(engine) as session:
        yield session
        session.rollback()


@pytest.fixture()
def fixture_company(db_session):
    company = db_session.scalar(select(Company).where(Company.ticker == _FIXTURE_TICKER))
    if company is None:
        company = Company(ticker=_FIXTURE_TICKER, company_name="Test Fixture Sentiment Co")
        db_session.add(company)
        db_session.commit()
    yield company


@pytest.fixture()
def fixture_source(db_session):
    source = db_session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == _FAKE_SOURCE_NAME))
    if source is None:
        source = DataSourceRegistry(
            name=_FAKE_SOURCE_NAME, category="news", access_type="documented_free",
            base_url="https://example.invalid", is_active=True,
        )
        db_session.add(source)
        db_session.commit()
    yield source


def _make_article(db_session, source, url: str, title: str) -> NewsArticle:
    now = dt.datetime.now(dt.UTC)
    article = NewsArticle(
        canonical_url=url, title=title, media_name="Test Media", language="id",
        credibility_tier=3, is_duplicate=False, cross_source_confirmed=False,
        source_id=source.id, retrieved_at=now, available_at=now,
        currency="IDR", unit="unit", is_restated=False, quality_status=QualityStatus.VALID,
    )
    db_session.add(article)
    db_session.commit()
    return article


@pytest.fixture(autouse=True)
def _cleanup(db_session, fixture_company, fixture_source):
    yield
    article_ids = [a.id for a in db_session.scalars(select(NewsArticle).where(NewsArticle.source_id == fixture_source.id)).all()]
    if article_ids:
        db_session.query(NewsSentiment).filter(NewsSentiment.article_id.in_(article_ids)).delete(synchronize_session=False)
        db_session.query(NewsEntity).filter(NewsEntity.article_id.in_(article_ids)).delete(synchronize_session=False)
        db_session.query(NewsArticle).filter(NewsArticle.id.in_(article_ids)).delete(synchronize_session=False)
    db_session.query(DataSourceRegistry).filter(DataSourceRegistry.id == fixture_source.id).delete()
    db_session.query(Company).filter(Company.ticker == _FIXTURE_TICKER).delete()
    db_session.commit()


def _fake_positive_scorer(text: str) -> SentimentModelResult:
    return SentimentModelResult(model_id=_MODEL_VERSION, raw_label="Positive", probabilities={"Positive": 0.9, "Neutral": 0.07, "Negative": 0.03})


def test_scores_entity_linked_article_and_writes_news_sentiment(db_session, fixture_company, fixture_source):
    article = _make_article(db_session, fixture_source, "https://example.invalid/s1", f"Saham {_FIXTURE_TICKER} melesat")
    db_session.add(NewsEntity(article_id=article.id, company_id=fixture_company.id))
    db_session.commit()

    outcome = compute_sentiment_for_unscored_pairs(
        db_session, model_version=_MODEL_VERSION, scorer=_fake_positive_scorer, company_ids=[fixture_company.id]
    )
    db_session.commit()

    assert outcome.pairs_scored == 1
    assert outcome.pairs_skipped_already_scored == 0

    row = db_session.scalar(
        select(NewsSentiment).where(NewsSentiment.article_id == article.id, NewsSentiment.company_id == fixture_company.id)
    )
    assert row is not None
    assert row.sentiment_label == "sangat_positif"
    assert row.model_version == _MODEL_VERSION
    assert float(row.sentiment_score) == pytest.approx(0.9 - 0.03)


def test_article_with_no_entity_link_gets_no_sentiment_row(db_session, fixture_company, fixture_source):
    article = _make_article(db_session, fixture_source, "https://example.invalid/s2", "Berita tanpa ticker apapun")
    # Scoped to fixture_company even though this article has no NewsEntity row at
    # all (irrelevant to what's being tested) -- an unscoped call here previously
    # ran across every real, already-entity-linked production article and wrote
    # fake sentiment rows for all of them (found live, cleaned up in the DB).
    compute_sentiment_for_unscored_pairs(
        db_session, model_version=_MODEL_VERSION, scorer=_fake_positive_scorer, company_ids=[fixture_company.id]
    )
    db_session.commit()

    # never joined into the query -- no NewsEntity row for this article at all
    rows = db_session.scalars(select(NewsSentiment).where(NewsSentiment.article_id == article.id)).all()
    assert rows == []


def test_rerun_with_same_model_version_skips_already_scored_pairs(db_session, fixture_company, fixture_source):
    article = _make_article(db_session, fixture_source, "https://example.invalid/s3", f"Kinerja {_FIXTURE_TICKER} solid")
    db_session.add(NewsEntity(article_id=article.id, company_id=fixture_company.id))
    db_session.commit()

    compute_sentiment_for_unscored_pairs(
        db_session, model_version=_MODEL_VERSION, scorer=_fake_positive_scorer, company_ids=[fixture_company.id]
    )
    db_session.commit()

    outcome_second = compute_sentiment_for_unscored_pairs(
        db_session, model_version=_MODEL_VERSION, scorer=_fake_positive_scorer, company_ids=[fixture_company.id]
    )
    db_session.commit()

    assert outcome_second.pairs_scored == 0
    assert outcome_second.pairs_skipped_already_scored == 1

    rows = db_session.scalars(
        select(NewsSentiment).where(NewsSentiment.article_id == article.id, NewsSentiment.company_id == fixture_company.id)
    ).all()
    assert len(rows) == 1  # not duplicated


def test_rerun_with_different_model_version_adds_a_second_row_not_overwrite(db_session, fixture_company, fixture_source):
    article = _make_article(db_session, fixture_source, "https://example.invalid/s4", f"Update {_FIXTURE_TICKER} hari ini")
    db_session.add(NewsEntity(article_id=article.id, company_id=fixture_company.id))
    db_session.commit()

    compute_sentiment_for_unscored_pairs(
        db_session, model_version=_MODEL_VERSION, scorer=_fake_positive_scorer, company_ids=[fixture_company.id]
    )
    db_session.commit()
    compute_sentiment_for_unscored_pairs(
        db_session, model_version="a-different-model-v2", scorer=_fake_positive_scorer, company_ids=[fixture_company.id]
    )
    db_session.commit()

    rows = db_session.scalars(
        select(NewsSentiment).where(NewsSentiment.article_id == article.id, NewsSentiment.company_id == fixture_company.id)
    ).all()
    assert len(rows) == 2  # both model versions' scores kept, never overwritten
    assert {r.model_version for r in rows} == {_MODEL_VERSION, "a-different-model-v2"}
