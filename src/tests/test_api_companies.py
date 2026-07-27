"""Integration tests for the companies API router -- requires a live
database (same DB the app itself connects to; ``get_session`` has no test
override, so ``TestClient`` hits the real DB through the real dependency).
Uses a disposable fixture company/sector (never real tickers), same
pattern as ``test_sector_pipeline.py``/``test_sentiment_pipeline.py``.
"""
from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.main import app
from src.database.models.company import Company, SectorRegistry
from src.database.models.features import TechnicalFeature
from src.database.models.fundamentals import FinancialRatio
from src.database.models.mixins import QualityStatus
from src.database.models.ml import RecommendationResult, ValuationResult
from src.database.models.news import NewsArticle, NewsEntity, NewsSentiment
from src.database.models.ops import DataSourceRegistry
from src.database.models.sector import SectorSpecificMetric
from src.database.session import make_engine

pytestmark = pytest.mark.integration

_FIXTURE_TICKER = "ZZZAPI"
_FIXTURE_INDEX_TICKER = "ZZZAPIIDX"
_FIXTURE_SECTOR_CODE = "zzztest_api_sector"
_FAKE_SOURCE_NAME = "fake_api_test_source"


@pytest.fixture()
def db_session():
    engine = make_engine("postgresql+psycopg://idx:idx@localhost:5433/idx_intelligence")
    with Session(engine) as session:
        yield session
        session.rollback()


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def fixture_source(db_session):
    source = db_session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == _FAKE_SOURCE_NAME))
    if source is None:
        source = DataSourceRegistry(
            name=_FAKE_SOURCE_NAME, category="internal_derived", access_type="internal_derived",
            base_url="internal://test", is_active=True,
        )
        db_session.add(source)
        db_session.commit()
    return source


@pytest.fixture()
def fixture_company(db_session):
    sector = db_session.scalar(select(SectorRegistry).where(SectorRegistry.sector_code == _FIXTURE_SECTOR_CODE))
    if sector is None:
        sector = SectorRegistry(
            sector_code=_FIXTURE_SECTOR_CODE, sector_name="Test Sector", subsector_name="Test Subsector",
            metrics_config_key="default", valuation_config_key="default",
        )
        db_session.add(sector)
        db_session.commit()

    company = db_session.scalar(select(Company).where(Company.ticker == _FIXTURE_TICKER))
    if company is None:
        company = Company(ticker=_FIXTURE_TICKER, company_name="Test Fixture API Co", sector_registry_id=sector.id)
        db_session.add(company)
        db_session.commit()
    yield company


@pytest.fixture()
def fixture_full_snapshot(db_session, fixture_company, fixture_source):
    """Populates one real row in every table the /snapshot endpoint reads from."""
    now = dt.datetime.now(dt.UTC)
    today = now.date()

    db_session.add(
        TechnicalFeature(
            company_id=fixture_company.id, feature_date=today, feature_name="rsi_14", value=55.5, feature_set_version="v1",
        )
    )
    db_session.add(
        FinancialRatio(
            company_id=fixture_company.id, ratio_name="roe__annual", value=0.15, is_applicable=True,
            computation_version="v1", source_id=fixture_source.id, retrieved_at=now, available_at=now,
            currency="IDR", unit="ratio", is_restated=False, quality_status=QualityStatus.VALID,
        )
    )
    db_session.add(
        SectorSpecificMetric(
            company_id=fixture_company.id, sector_registry_id=fixture_company.sector_registry_id,
            metric_name="roe_percentile_in_sector", value=80.0, source_id=fixture_source.id,
            retrieved_at=now, available_at=now, currency="IDR", unit="percentile", is_restated=False,
            quality_status=QualityStatus.VALID,
        )
    )
    db_session.add(
        ValuationResult(
            company_id=fixture_company.id, as_of_date=today, methods_used={"relative_pe_historical": 1.0},
            fair_value_bear=1000.0, fair_value_base=1200.0, fair_value_bull=1500.0,
            fair_value_conservative=900.0, data_quality_score=0.9,
        )
    )
    db_session.add(
        RecommendationResult(
            company_id=fixture_company.id, as_of_date=today, label="HOLD", confidence=0.75,
            scores={"roe": 0.15}, suggested_horizon="6-12 bulan",
        )
    )
    db_session.commit()


@pytest.fixture()
def fixture_news_with_sentiment(db_session, fixture_company, fixture_source):
    article = NewsArticle(
        canonical_url="https://example.invalid/api-test-1", title=f"Berita {_FIXTURE_TICKER} hari ini",
        media_name="Test Media", language="id", credibility_tier=3, is_duplicate=False,
        cross_source_confirmed=False, source_id=fixture_source.id,
        retrieved_at=dt.datetime.now(dt.UTC), available_at=dt.datetime.now(dt.UTC),
        currency="IDR", unit="unit", is_restated=False, quality_status=QualityStatus.VALID,
        published_at=dt.datetime.now(dt.UTC),
    )
    db_session.add(article)
    db_session.commit()
    db_session.add(NewsEntity(article_id=article.id, company_id=fixture_company.id))
    db_session.add(
        NewsSentiment(
            article_id=article.id, company_id=fixture_company.id, sentiment_label="positif",
            sentiment_score=0.4, model_version="test-model",
        )
    )
    db_session.commit()
    return article


@pytest.fixture(autouse=True)
def _cleanup(db_session, fixture_company, fixture_source):
    yield
    db_session.query(NewsSentiment).filter(NewsSentiment.company_id == fixture_company.id).delete()
    db_session.query(NewsEntity).filter(NewsEntity.company_id == fixture_company.id).delete()
    article_ids = [a.id for a in db_session.scalars(select(NewsArticle).where(NewsArticle.source_id == fixture_source.id)).all()]
    if article_ids:
        db_session.query(NewsArticle).filter(NewsArticle.id.in_(article_ids)).delete(synchronize_session=False)
    db_session.query(TechnicalFeature).filter(TechnicalFeature.company_id == fixture_company.id).delete()
    db_session.query(FinancialRatio).filter(FinancialRatio.company_id == fixture_company.id).delete()
    db_session.query(SectorSpecificMetric).filter(SectorSpecificMetric.company_id == fixture_company.id).delete()
    db_session.query(ValuationResult).filter(ValuationResult.company_id == fixture_company.id).delete()
    db_session.query(RecommendationResult).filter(RecommendationResult.company_id == fixture_company.id).delete()
    db_session.query(DataSourceRegistry).filter(DataSourceRegistry.id == fixture_source.id).delete()
    db_session.query(Company).filter(Company.ticker == _FIXTURE_TICKER).delete()
    db_session.query(Company).filter(Company.ticker == _FIXTURE_INDEX_TICKER).delete()
    db_session.query(SectorRegistry).filter(SectorRegistry.sector_code == _FIXTURE_SECTOR_CODE).delete()
    db_session.commit()


def test_list_companies_search_by_ticker(client, fixture_company):
    resp = client.get(f"/api/v1/companies?q={_FIXTURE_TICKER}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["ticker"] == _FIXTURE_TICKER
    assert body["items"][0]["asset_type"] == "equity"
    assert body["items"][0]["sector_name"] == "Test Sector"


def test_get_company_detail(client, fixture_company):
    resp = client.get(f"/api/v1/companies/{_FIXTURE_TICKER}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["company_name"] == "Test Fixture API Co"
    assert body["asset_type"] == "equity"
    assert body["subsector_name"] == "Test Subsector"


def test_company_list_defaults_to_equity_but_can_include_index(client, db_session):
    db_session.add(
        Company(
            ticker=_FIXTURE_INDEX_TICKER,
            company_name="Test API Index",
            asset_type="index",
        )
    )
    db_session.commit()

    default_resp = client.get(f"/api/v1/companies?q={_FIXTURE_INDEX_TICKER}")
    all_resp = client.get(
        f"/api/v1/companies?q={_FIXTURE_INDEX_TICKER}&asset_type=all"
    )
    detail_resp = client.get(f"/api/v1/companies/{_FIXTURE_INDEX_TICKER}")

    assert default_resp.status_code == 200
    assert default_resp.json()["total"] == 0
    assert all_resp.status_code == 200
    assert all_resp.json()["items"][0]["asset_type"] == "index"
    assert detail_resp.status_code == 200
    assert detail_resp.json()["asset_type"] == "index"


def test_get_company_detail_unknown_ticker_is_404(client):
    resp = client.get("/api/v1/companies/ZZZDOESNOTEXIST")
    assert resp.status_code == 404


def test_snapshot_returns_latest_value_per_feature_and_all_result_sections(client, fixture_company, fixture_full_snapshot):
    resp = client.get(f"/api/v1/companies/{_FIXTURE_TICKER}/snapshot")
    assert resp.status_code == 200
    body = resp.json()

    assert {item["name"]: item["value"] for item in body["technical"]} == {"rsi_14": 55.5}
    assert {item["name"]: item["value"] for item in body["fundamental_ratios"]} == {"roe__annual": 0.15}
    assert {item["name"]: item["value"] for item in body["sector_relative_metrics"]} == {"roe_percentile_in_sector": 80.0}

    assert body["valuation"]["fair_value_base"] == 1200.0
    assert body["recommendation"]["label"] == "HOLD"
    assert body["recommendation"]["confidence"] == 0.75


def test_snapshot_with_no_computed_results_has_empty_lists_and_null_sections(client, fixture_company):
    resp = client.get(f"/api/v1/companies/{_FIXTURE_TICKER}/snapshot")
    assert resp.status_code == 200
    body = resp.json()
    assert body["technical"] == []
    assert body["fundamental_ratios"] == []
    assert body["valuation"] is None
    assert body["recommendation"] is None


def test_company_news_includes_sentiment(client, fixture_company, fixture_news_with_sentiment):
    resp = client.get(f"/api/v1/companies/{_FIXTURE_TICKER}/news")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["sentiment_label"] == "positif"
    assert body["items"][0]["sentiment_score"] == pytest.approx(0.4)


def test_company_news_empty_when_no_articles(client, fixture_company):
    resp = client.get(f"/api/v1/companies/{_FIXTURE_TICKER}/news")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0, "offset": 0, "limit": 20}
