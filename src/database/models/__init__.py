"""Import every model module so Base.metadata is fully populated.

Alembic's env.py imports this package to get target_metadata for
autogeneration -- a model defined but not imported here is invisible to
migrations.
"""
from src.database.models import (  # noqa: F401
    company,
    features,
    fundamentals,
    macro,
    market,
    ml,
    news,
    ops,
    sector,
)
from src.database.models.company import Company, CompanyAlias, SectorRegistry
from src.database.models.features import FundamentalFeature, ModelFeatures, TechnicalFeature
from src.database.models.fundamentals import (
    FinancialRatio,
    FinancialStatementItem,
    FinancialStatementRaw,
)
from src.database.models.macro import IndustrySeries, MacroSeries
from src.database.models.market import CorporateAction, Dividend, MarketPriceClean, MarketPriceRaw
from src.database.models.ml import (
    ModelVersion,
    Prediction,
    RecommendationResult,
    TrainingRun,
    ValuationResult,
)
from src.database.models.news import NewsArticle, NewsEntity, NewsSentiment, ReputationEvent
from src.database.models.ops import Alert, DataQualityResult, DataSourceRegistry, PipelineRun
from src.database.models.sector import SectorSpecificMetric

__all__ = [
    "Alert",
    "Company",
    "CompanyAlias",
    "CorporateAction",
    "DataQualityResult",
    "DataSourceRegistry",
    "Dividend",
    "FinancialRatio",
    "FinancialStatementItem",
    "FinancialStatementRaw",
    "FundamentalFeature",
    "IndustrySeries",
    "MacroSeries",
    "MarketPriceClean",
    "MarketPriceRaw",
    "ModelFeatures",
    "ModelVersion",
    "NewsArticle",
    "NewsEntity",
    "NewsSentiment",
    "PipelineRun",
    "Prediction",
    "RecommendationResult",
    "ReputationEvent",
    "SectorRegistry",
    "SectorSpecificMetric",
    "TechnicalFeature",
    "TrainingRun",
    "ValuationResult",
]
