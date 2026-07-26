"""Integration tests for the recommendation pipeline -- requires a live
database. Uses a fixture company (never a real ticker's row) -- see
``test_ingestion_fundamentals.py``'s module docstring for why.
"""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models.company import Company
from src.database.models.fundamentals import FinancialRatio
from src.database.models.mixins import QualityStatus
from src.database.models.ml import RecommendationResult, ValuationResult
from src.database.models.news import NewsArticle, NewsEntity, NewsSentiment
from src.database.models.ops import DataSourceRegistry
from src.database.session import make_engine
from src.recommendation.pipeline import compute_recommendation
from src.recommendation.scoring import LABEL_DATA_TIDAK_MENCUKUPI, LABEL_LAYAK_DIBELI

pytestmark = pytest.mark.integration


@pytest.fixture()
def db_session():
    engine = make_engine("postgresql+psycopg://idx:idx@localhost:5433/idx_intelligence")
    with Session(engine) as session:
        yield session
        session.rollback()


def _make_source(session: Session, name: str) -> DataSourceRegistry:
    source = session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == name))
    if source is None:
        source = DataSourceRegistry(name=name, category="fundamentals", access_type="internal_derived", is_active=True)
        session.add(source)
        session.flush()
    return source


@pytest.fixture()
def company_with_recommendation_inputs(db_session):
    company = db_session.scalar(select(Company).where(Company.ticker == "ZZZR2"))
    if company is None:
        company = Company(ticker="ZZZR2", company_name="Test Fixture Recommendation Co")
        db_session.add(company)
        db_session.flush()
    source = _make_source(db_session, "fake_recommendation_source")
    now = dt.datetime.now(dt.UTC)

    db_session.add(
        ValuationResult(
            company_id=company.id,
            as_of_date=dt.date(2026, 7, 24),
            methods_used={"relative_pe_historical": 0.5, "relative_pb_historical": 0.5},
            fair_value_bear=100.0,
            fair_value_base=120.0,
            fair_value_bull=150.0,
            fair_value_conservative=90.0,
            sensitivity={"current_price": 80.0, "current_price_date": "2026-07-24"},  # below bear -> undervalued
            data_quality_score=1.0,
        )
    )
    db_session.add_all(
        [
            FinancialRatio(
                company_id=company.id, ratio_name="net_margin__annual", value=0.15, is_applicable=True,
                computation_version="v1", source_id=source.id, retrieved_at=now,
                available_at=dt.datetime(2026, 4, 30, tzinfo=dt.UTC), period_end=dt.date(2025, 12, 31),
                currency="IDR", unit="unit", is_restated=False, quality_status=QualityStatus.VALID,
            ),
            FinancialRatio(
                company_id=company.id, ratio_name="roe__annual", value=0.20, is_applicable=True,
                computation_version="v1", source_id=source.id, retrieved_at=now,
                available_at=dt.datetime(2026, 4, 30, tzinfo=dt.UTC), period_end=dt.date(2025, 12, 31),
                currency="IDR", unit="unit", is_restated=False, quality_status=QualityStatus.VALID,
            ),
            FinancialRatio(
                company_id=company.id, ratio_name="debt_to_equity__annual", value=0.4, is_applicable=True,
                computation_version="v1", source_id=source.id, retrieved_at=now,
                available_at=dt.datetime(2026, 4, 30, tzinfo=dt.UTC), period_end=dt.date(2025, 12, 31),
                currency="IDR", unit="unit", is_restated=False, quality_status=QualityStatus.VALID,
            ),
        ]
    )
    db_session.commit()
    yield company
    db_session.query(RecommendationResult).filter(RecommendationResult.company_id == company.id).delete()
    db_session.query(ValuationResult).filter(ValuationResult.company_id == company.id).delete()
    db_session.query(FinancialRatio).filter(FinancialRatio.company_id == company.id).delete()
    db_session.query(Company).filter(Company.id == company.id).delete()
    db_session.query(DataSourceRegistry).filter(DataSourceRegistry.name == "fake_recommendation_source").delete()
    db_session.commit()


@pytest.fixture()
def negative_sentiment_for_company(db_session, company_with_recommendation_inputs):
    company = company_with_recommendation_inputs
    source = _make_source(db_session, "fake_recommendation_source")
    now = dt.datetime.now(dt.UTC)
    article = NewsArticle(
        canonical_url="https://example.invalid/rec-sentiment-1", title="Berita ZZZR2 buruk",
        media_name="Test Media", language="id", credibility_tier=3, is_duplicate=False,
        cross_source_confirmed=False, source_id=source.id, retrieved_at=now, available_at=now,
        currency="IDR", unit="unit", is_restated=False, quality_status=QualityStatus.VALID, published_at=now,
    )
    db_session.add(article)
    db_session.commit()
    db_session.add(NewsEntity(article_id=article.id, company_id=company.id))
    db_session.add(
        NewsSentiment(
            article_id=article.id, company_id=company.id, sentiment_label="sangat_negatif",
            sentiment_score=-0.8, model_version="test-model",
        )
    )
    db_session.commit()
    yield company
    db_session.query(NewsSentiment).filter(NewsSentiment.company_id == company.id).delete()
    db_session.query(NewsEntity).filter(NewsEntity.company_id == company.id).delete()
    db_session.query(NewsArticle).filter(NewsArticle.id == article.id).delete()
    db_session.commit()


def test_compute_recommendation_negative_sentiment_triggers_guardrail_but_not_label(
    db_session, negative_sentiment_for_company
):
    company = negative_sentiment_for_company
    outcome = compute_recommendation(db_session, "ZZZR2", as_of_date=dt.date(2026, 7, 24))
    db_session.commit()

    # sentiment is a guardrail flag only -- valuation+fundamentals still drive the label
    assert outcome.label == LABEL_LAYAK_DIBELI

    result = db_session.scalar(
        select(RecommendationResult).where(
            RecommendationResult.company_id == company.id, RecommendationResult.as_of_date == dt.date(2026, 7, 24)
        )
    )
    assert result.guardrails_triggered is not None
    assert "recent_negative_sentiment" in result.guardrails_triggered
    assert result.scores["sentiment_label"] == "sangat_negatif"
    assert result.scores["sentiment_score"] == pytest.approx(-0.8)
    assert result.scores["sentiment_signal_used"] is True


def test_compute_recommendation_no_sentiment_data_records_none_and_no_guardrail(
    db_session, company_with_recommendation_inputs
):
    company = company_with_recommendation_inputs
    compute_recommendation(db_session, "ZZZR2", as_of_date=dt.date(2026, 7, 24))
    db_session.commit()

    result = db_session.scalar(
        select(RecommendationResult).where(
            RecommendationResult.company_id == company.id, RecommendationResult.as_of_date == dt.date(2026, 7, 24)
        )
    )
    assert result.scores["sentiment_label"] is None
    assert result.scores["sentiment_score"] is None
    assert result.scores["sentiment_signal_used"] is False
    assert "recent_negative_sentiment" not in (result.guardrails_triggered or [])


def test_compute_recommendation_undervalued_healthy_is_layak_dibeli(db_session, company_with_recommendation_inputs):
    company = company_with_recommendation_inputs
    outcome = compute_recommendation(db_session, "ZZZR2", as_of_date=dt.date(2026, 7, 24))
    db_session.commit()

    assert outcome.skipped_reason is None
    assert outcome.label == LABEL_LAYAK_DIBELI
    assert outcome.confidence == 1.0

    result = db_session.scalar(
        select(RecommendationResult).where(
            RecommendationResult.company_id == company.id, RecommendationResult.as_of_date == dt.date(2026, 7, 24)
        )
    )
    assert result is not None
    assert result.label == LABEL_LAYAK_DIBELI
    assert result.scores["ml_signal_used"] is False  # explicit, not an accidental omission
    assert result.entry_zone == {"low": 90.0, "high": 120.0}
    assert result.suggested_horizon == "6-12 bulan"
    assert result.investment_style is None  # not fabricated


def test_compute_recommendation_is_idempotent_per_day_not_across_days(db_session, company_with_recommendation_inputs):
    company = company_with_recommendation_inputs
    compute_recommendation(db_session, "ZZZR2", as_of_date=dt.date(2026, 7, 23))
    db_session.commit()
    compute_recommendation(db_session, "ZZZR2", as_of_date=dt.date(2026, 7, 23))  # rerun same day
    db_session.commit()
    compute_recommendation(db_session, "ZZZR2", as_of_date=dt.date(2026, 7, 24))  # a different day
    db_session.commit()

    rows = db_session.scalars(select(RecommendationResult).where(RecommendationResult.company_id == company.id)).all()
    dates = sorted(r.as_of_date for r in rows)
    assert dates == [dt.date(2026, 7, 23), dt.date(2026, 7, 24)]


def test_compute_recommendation_skips_unknown_ticker(db_session):
    outcome = compute_recommendation(db_session, "NOPE_NOT_REAL")
    assert outcome.skipped_reason is not None


def test_compute_recommendation_skips_when_no_valuation(db_session):
    company = Company(ticker="ZZZR3", company_name="No Valuation Yet")
    db_session.add(company)
    db_session.commit()
    try:
        outcome = compute_recommendation(db_session, "ZZZR3")
        assert outcome.skipped_reason is not None
        assert "valuation" in outcome.skipped_reason
    finally:
        db_session.query(Company).filter(Company.id == company.id).delete()
        db_session.commit()


def test_compute_recommendation_missing_fundamentals_is_data_tidak_mencukupi(db_session):
    company = Company(ticker="ZZZR4", company_name="Valuation Only, No Fundamentals")
    db_session.add(company)
    db_session.flush()
    db_session.add(
        ValuationResult(
            company_id=company.id, as_of_date=dt.date(2026, 7, 24),
            methods_used={"relative_pb_historical": 1.0}, fair_value_bear=100.0, fair_value_base=120.0,
            fair_value_bull=150.0, fair_value_conservative=90.0,
            sensitivity={"current_price": 80.0, "current_price_date": "2026-07-24"}, data_quality_score=0.5,
        )
    )
    db_session.commit()
    try:
        outcome = compute_recommendation(db_session, "ZZZR4", as_of_date=dt.date(2026, 7, 24))
        assert outcome.label == LABEL_DATA_TIDAK_MENCUKUPI
    finally:
        db_session.query(RecommendationResult).filter(RecommendationResult.company_id == company.id).delete()
        db_session.query(ValuationResult).filter(ValuationResult.company_id == company.id).delete()
        db_session.query(Company).filter(Company.id == company.id).delete()
        db_session.commit()
