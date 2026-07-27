"""Read-only response models for the API (spec section 26). Every field
here mirrors a real DB column -- nothing computed or narrated by this
layer; the API only ever serializes what the pipelines already wrote.
"""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class CompanyListItem(BaseModel):
    ticker: str
    company_name: str
    asset_type: str
    sector_name: str | None = None
    listing_board: str | None = None
    status: str


class CompanyDetail(BaseModel):
    ticker: str
    company_name: str
    asset_type: str
    sector_name: str | None = None
    subsector_name: str | None = None
    listing_board: str | None = None
    listing_date: dt.date | None = None
    status: str


class NamedValue(BaseModel):
    name: str
    value: float | None
    as_of: dt.date | None = None


class ValuationSnapshot(BaseModel):
    as_of_date: dt.date
    methods_used: dict
    fair_value_bear: float | None
    fair_value_base: float | None
    fair_value_bull: float | None
    fair_value_conservative: float | None
    data_quality_score: float | None


class RecommendationSnapshot(BaseModel):
    as_of_date: dt.date
    label: str
    confidence: float
    scores: dict
    guardrails_triggered: list | None
    entry_zone: dict | None
    investment_style: str | None
    suggested_horizon: str | None


class CompanySnapshot(BaseModel):
    company: CompanyDetail
    technical: list[NamedValue]
    fundamental_ratios: list[NamedValue]
    sector_relative_metrics: list[NamedValue]
    valuation: ValuationSnapshot | None
    recommendation: RecommendationSnapshot | None


class NewsItem(BaseModel):
    title: str
    media_name: str
    canonical_url: str
    published_at: dt.datetime | None
    credibility_tier: int
    sentiment_label: str | None = None
    sentiment_score: float | None = None


class RecommendationScreenerItem(BaseModel):
    ticker: str
    company_name: str
    as_of_date: dt.date
    label: str
    confidence: float


class CompanyListResponse(BaseModel):
    items: list[CompanyListItem]
    total: int
    offset: int
    limit: int


class RecommendationScreenerResponse(BaseModel):
    items: list[RecommendationScreenerItem]
    total: int
    offset: int
    limit: int


class NewsListResponse(BaseModel):
    items: list[NewsItem]
    total: int
    offset: int
    limit: int
