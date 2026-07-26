"""Integration tests for the recommendations screener API -- requires a
live database. Uses a disposable fixture company/label combination that
cannot collide with real production recommendations (a label no real
pipeline run would produce, plus a fixture ticker).
"""
from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.main import app
from src.database.models.company import Company
from src.database.models.ml import RecommendationResult
from src.database.session import make_engine

pytestmark = pytest.mark.integration

_FIXTURE_TICKER = "ZZZRECAPI"
_FIXTURE_LABEL = "LAYAK_DIBELI"


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
def fixture_company(db_session):
    company = db_session.scalar(select(Company).where(Company.ticker == _FIXTURE_TICKER))
    if company is None:
        company = Company(ticker=_FIXTURE_TICKER, company_name="Test Fixture Recommendation Co")
        db_session.add(company)
        db_session.commit()
    yield company


@pytest.fixture()
def fixture_two_recommendation_rows(db_session, fixture_company):
    """An older + a newer row for the same company -- the screener must
    surface only the newer one (max as_of_date per company)."""
    older = RecommendationResult(
        company_id=fixture_company.id, as_of_date=dt.date(2020, 1, 1), label="HOLD",
        confidence=0.5, scores={},
    )
    newer = RecommendationResult(
        company_id=fixture_company.id, as_of_date=dt.datetime.now(dt.UTC).date(), label=_FIXTURE_LABEL,
        confidence=0.99, scores={},
    )
    db_session.add_all([older, newer])
    db_session.commit()


@pytest.fixture(autouse=True)
def _cleanup(db_session, fixture_company):
    yield
    db_session.query(RecommendationResult).filter(RecommendationResult.company_id == fixture_company.id).delete()
    db_session.query(Company).filter(Company.ticker == _FIXTURE_TICKER).delete()
    db_session.commit()


def test_screener_returns_only_latest_row_per_company(client, fixture_company, fixture_two_recommendation_rows):
    resp = client.get(f"/api/v1/recommendations?label={_FIXTURE_LABEL}")
    assert resp.status_code == 200
    body = resp.json()
    matches = [item for item in body["items"] if item["ticker"] == _FIXTURE_TICKER]
    assert len(matches) == 1
    assert matches[0]["label"] == _FIXTURE_LABEL
    assert matches[0]["confidence"] == pytest.approx(0.99)
    assert matches[0]["as_of_date"] == dt.datetime.now(dt.UTC).date().isoformat()


def test_screener_label_filter_excludes_other_labels(client, fixture_company, fixture_two_recommendation_rows):
    resp = client.get("/api/v1/recommendations?label=HINDARI")
    assert resp.status_code == 200
    tickers = {item["ticker"] for item in resp.json()["items"]}
    assert _FIXTURE_TICKER not in tickers
