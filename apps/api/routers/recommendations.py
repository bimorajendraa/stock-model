"""Recommendation screener (spec section 26): each company's most recent
``recommendation_results`` row, filterable/sortable -- read-only, computes
nothing new.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.schemas import RecommendationScreenerItem, RecommendationScreenerResponse
from src.database.models.company import Company
from src.database.models.ml import RecommendationResult
from src.database.session import get_session

router = APIRouter(prefix="/api/v1/recommendations", tags=["recommendations"])

_VALID_LABELS = {
    "LAYAK_DIBELI",
    "AKUMULASI_BERTAHAP",
    "TUNGGU_HARGA",
    "HOLD",
    "HINDARI",
    "DATA_TIDAK_MENCUKUPI",
}


def _latest_recommendation_subquery():
    # one row per company: the RecommendationResult with the max as_of_date
    return (
        select(
            RecommendationResult.company_id,
            func.max(RecommendationResult.as_of_date).label("latest_date"),
        )
        .group_by(RecommendationResult.company_id)
        .subquery()
    )


@router.get("", response_model=RecommendationScreenerResponse)
def list_recommendations(
    label: str | None = Query(default=None, description=f"Filter by label, one of {sorted(_VALID_LABELS)}"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> RecommendationScreenerResponse:
    latest = _latest_recommendation_subquery()
    stmt = (
        select(RecommendationResult, Company)
        .join(
            latest,
            (RecommendationResult.company_id == latest.c.company_id)
            & (RecommendationResult.as_of_date == latest.c.latest_date),
        )
        .join(Company, Company.id == RecommendationResult.company_id)
    )
    if label:
        stmt = stmt.where(RecommendationResult.label == label)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = session.scalar(count_stmt) or 0

    rows = session.execute(
        stmt.order_by(RecommendationResult.confidence.desc()).offset(offset).limit(limit)
    ).all()

    items = [
        RecommendationScreenerItem(
            ticker=company.ticker,
            company_name=company.company_name,
            as_of_date=rec.as_of_date,
            label=rec.label,
            confidence=rec.confidence,
        )
        for rec, company in rows
    ]
    return RecommendationScreenerResponse(items=items, total=total, offset=offset, limit=limit)
