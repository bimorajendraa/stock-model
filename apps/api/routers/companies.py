"""Company list/detail + per-company computed-result snapshot (spec
section 26). Read-only: every value returned here is exactly what the
relevant pipeline (features/valuation/recommendation/sentiment) already
wrote -- this layer computes nothing.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.schemas import (
    CompanyDetail,
    CompanyListItem,
    CompanyListResponse,
    CompanySnapshot,
    NamedValue,
    NewsItem,
    NewsListResponse,
    RecommendationSnapshot,
    ValuationSnapshot,
)
from src.database.models.company import Company, SectorRegistry
from src.database.models.features import TechnicalFeature
from src.database.models.fundamentals import FinancialRatio
from src.database.models.ml import RecommendationResult, ValuationResult
from src.database.models.news import NewsArticle, NewsEntity, NewsSentiment
from src.database.models.sector import SectorSpecificMetric
from src.database.session import get_session

router = APIRouter(prefix="/api/v1/companies", tags=["companies"])


def _get_company_or_404(session: Session, ticker: str) -> Company:
    company = session.scalar(select(Company).where(Company.ticker == ticker.upper()))
    if company is None:
        raise HTTPException(status_code=404, detail=f"no company with ticker {ticker!r}")
    return company


def _latest_named_values(rows: list[tuple[str, float | None]]) -> list[NamedValue]:
    """``rows`` must already be ordered newest-first -- keeps the first
    (i.e. latest) occurrence per name, matching the dedup-by-latest
    pattern used throughout ``src/features``/``src/valuation``."""
    seen: dict[str, float | None] = {}
    for name, value in rows:
        if name not in seen:
            seen[name] = value
    return [NamedValue(name=name, value=value) for name, value in seen.items()]


@router.get("", response_model=CompanyListResponse)
def list_companies(
    q: str | None = Query(default=None, description="Filter by ticker or company name substring"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> CompanyListResponse:
    stmt = select(Company).outerjoin(SectorRegistry, Company.sector_registry_id == SectorRegistry.id)
    count_stmt = select(func.count()).select_from(Company)
    if q:
        pattern = f"%{q}%"
        text_filter = (Company.ticker.ilike(pattern)) | (Company.company_name.ilike(pattern))
        stmt = stmt.where(text_filter)
        count_stmt = count_stmt.where(text_filter)

    total = session.scalar(count_stmt) or 0
    rows = session.execute(
        stmt.add_columns(SectorRegistry.sector_name).order_by(Company.ticker).offset(offset).limit(limit)
    ).all()

    items = [
        CompanyListItem(
            ticker=company.ticker,
            company_name=company.company_name,
            sector_name=sector_name,
            listing_board=company.listing_board,
            status=company.status,
        )
        for company, sector_name in rows
    ]
    return CompanyListResponse(items=items, total=total, offset=offset, limit=limit)


@router.get("/{ticker}", response_model=CompanyDetail)
def get_company(ticker: str, session: Session = Depends(get_session)) -> CompanyDetail:
    company = _get_company_or_404(session, ticker)
    sector = session.get(SectorRegistry, company.sector_registry_id) if company.sector_registry_id else None
    return CompanyDetail(
        ticker=company.ticker,
        company_name=company.company_name,
        sector_name=sector.sector_name if sector else None,
        subsector_name=sector.subsector_name if sector else None,
        listing_board=company.listing_board,
        listing_date=company.listing_date,
        status=company.status,
    )


@router.get("/{ticker}/snapshot", response_model=CompanySnapshot)
def get_company_snapshot(ticker: str, session: Session = Depends(get_session)) -> CompanySnapshot:
    company = _get_company_or_404(session, ticker)
    company_detail = get_company(ticker, session)

    technical_rows = session.execute(
        select(TechnicalFeature.feature_name, TechnicalFeature.value)
        .where(TechnicalFeature.company_id == company.id)
        .order_by(TechnicalFeature.feature_date.desc())
    ).all()

    ratio_rows = session.execute(
        select(FinancialRatio.ratio_name, FinancialRatio.value)
        .where(FinancialRatio.company_id == company.id, FinancialRatio.is_applicable.is_(True))
        .order_by(FinancialRatio.available_at.desc())
    ).all()

    sector_metric_rows = session.execute(
        select(SectorSpecificMetric.metric_name, SectorSpecificMetric.value)
        .where(SectorSpecificMetric.company_id == company.id)
        .order_by(SectorSpecificMetric.available_at.desc())
    ).all()

    valuation_row = session.execute(
        select(ValuationResult).where(ValuationResult.company_id == company.id).order_by(ValuationResult.as_of_date.desc())
    ).scalars().first()

    recommendation_row = (
        session.execute(
            select(RecommendationResult)
            .where(RecommendationResult.company_id == company.id)
            .order_by(RecommendationResult.as_of_date.desc())
        )
        .scalars()
        .first()
    )

    return CompanySnapshot(
        company=company_detail,
        technical=_latest_named_values(list(technical_rows)),
        fundamental_ratios=_latest_named_values(list(ratio_rows)),
        sector_relative_metrics=_latest_named_values(list(sector_metric_rows)),
        valuation=(
            ValuationSnapshot(
                as_of_date=valuation_row.as_of_date,
                methods_used=valuation_row.methods_used,
                fair_value_bear=valuation_row.fair_value_bear,
                fair_value_base=valuation_row.fair_value_base,
                fair_value_bull=valuation_row.fair_value_bull,
                fair_value_conservative=valuation_row.fair_value_conservative,
                data_quality_score=valuation_row.data_quality_score,
            )
            if valuation_row is not None
            else None
        ),
        recommendation=(
            RecommendationSnapshot(
                as_of_date=recommendation_row.as_of_date,
                label=recommendation_row.label,
                confidence=recommendation_row.confidence,
                scores=recommendation_row.scores,
                guardrails_triggered=recommendation_row.guardrails_triggered,
                entry_zone=recommendation_row.entry_zone,
                investment_style=recommendation_row.investment_style,
                suggested_horizon=recommendation_row.suggested_horizon,
            )
            if recommendation_row is not None
            else None
        ),
    )


@router.get("/{ticker}/news", response_model=NewsListResponse)
def get_company_news(
    ticker: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> NewsListResponse:
    company = _get_company_or_404(session, ticker)

    base_stmt = (
        select(NewsArticle, NewsSentiment.sentiment_label, NewsSentiment.sentiment_score)
        .join(NewsEntity, NewsEntity.article_id == NewsArticle.id)
        .outerjoin(
            NewsSentiment,
            (NewsSentiment.article_id == NewsArticle.id) & (NewsSentiment.company_id == company.id),
        )
        .where(NewsEntity.company_id == company.id)
    )
    total = session.scalar(
        select(func.count()).select_from(
            select(NewsArticle.id).join(NewsEntity, NewsEntity.article_id == NewsArticle.id).where(NewsEntity.company_id == company.id).subquery()
        )
    ) or 0

    rows = session.execute(
        base_stmt.order_by(NewsArticle.published_at.desc()).offset(offset).limit(limit)
    ).all()

    items = [
        NewsItem(
            title=article.title,
            media_name=article.media_name,
            canonical_url=article.canonical_url,
            published_at=article.published_at,
            credibility_tier=article.credibility_tier,
            sentiment_label=sentiment_label,
            sentiment_score=float(sentiment_score) if sentiment_score is not None else None,
        )
        for article, sentiment_label, sentiment_score in rows
    ]
    return NewsListResponse(items=items, total=total, offset=offset, limit=limit)
