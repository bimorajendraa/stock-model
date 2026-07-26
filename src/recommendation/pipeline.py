"""valuation_results + financial_ratios -> recommendation_results (spec
section 21), via the deterministic scoring in ``scoring.py``.

Same day-scoped idempotency as ``valuation_results``
(``src/valuation/pipeline.py``'s docstring): recommendation_results
accumulates a real history of daily snapshots, so re-running today
replaces only today's row.
"""
from __future__ import annotations

import dataclasses
import datetime as dt

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.database.models.company import Company
from src.database.models.fundamentals import FinancialRatio
from src.database.models.ml import RecommendationResult, ValuationResult
from src.database.models.news import NewsArticle, NewsSentiment
from src.recommendation.scoring import (
    LABEL_AKUMULASI_BERTAHAP,
    LABEL_LAYAK_DIBELI,
    LABEL_TUNGGU_HARGA,
    classify_fundamental_quality,
    classify_valuation_position,
    combine_recommendation,
    compute_confidence,
)

_SUGGESTED_HORIZON = "6-12 bulan"  # documented assumption behind the self-relative valuation's implicit mean-reversion thesis, not derived from data

_NET_MARGIN_NAMES = ("net_margin__annual", "net_margin__quarterly")
_ROE_NAMES = ("roe__annual", "roe__quarterly")
_DEBT_TO_EQUITY_NAMES = ("debt_to_equity__annual", "debt_to_equity__quarterly")

# Only a guardrail *flag*, never a label/confidence override -- same
# discipline as excluding the ML signal (module docstring): the sentiment
# model (docs/sentiment.md) has a real, documented bias toward "netral" on
# terse financial headlines (28/29 real pairs scored netral in the run
# that doc records), so its *presence* here is meaningful (the model
# rarely misreads genuinely positive news as negative) but its *absence*
# must never be read as "no negative news" -- most real negative news gets
# missed as netral, not caught as false-negative.
_NEGATIVE_SENTIMENT_LABELS = {"negatif", "sangat_negatif"}


@dataclasses.dataclass
class RecommendationOutcome:
    ticker: str
    as_of_date: dt.date | None = None
    label: str | None = None
    confidence: float | None = None
    skipped_reason: str | None = None


def _latest_ratio_value(session: Session, company_id: int, ratio_names: tuple[str, ...]) -> float | None:
    row = session.execute(
        select(FinancialRatio.value)
        .where(
            FinancialRatio.company_id == company_id,
            FinancialRatio.ratio_name.in_(ratio_names),
            FinancialRatio.is_applicable.is_(True),
        )
        .order_by(FinancialRatio.available_at.desc())
    ).first()
    return float(row[0]) if row and row[0] is not None else None


def _latest_sentiment(session: Session, company_id: int) -> tuple[str | None, float | None]:
    """Most recent (by the article's own ``published_at``, not scoring
    time) ``news_sentiment`` row linked to this company across every
    model_version -- informational only, see the guardrail comment above
    for why this never drives the label/confidence itself."""
    row = session.execute(
        select(NewsSentiment.sentiment_label, NewsSentiment.sentiment_score)
        .join(NewsArticle, NewsArticle.id == NewsSentiment.article_id)
        .where(NewsSentiment.company_id == company_id)
        .order_by(NewsArticle.published_at.desc())
    ).first()
    if row is None:
        return None, None
    label, score = row
    return label, (float(score) if score is not None else None)


def compute_recommendation(session: Session, ticker: str, as_of_date: dt.date | None = None) -> RecommendationOutcome:
    as_of_date = as_of_date or dt.datetime.now(dt.UTC).date()
    outcome = RecommendationOutcome(ticker=ticker, as_of_date=as_of_date)

    company = session.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        outcome.skipped_reason = "no matching Company row"
        return outcome

    valuation = session.scalar(
        select(ValuationResult)
        .where(ValuationResult.company_id == company.id)
        .order_by(ValuationResult.as_of_date.desc())
    )
    if valuation is None:
        outcome.skipped_reason = "no valuation_results row -- run valuation compute first"
        return outcome

    current_price = valuation.sensitivity.get("current_price") if valuation.sensitivity else None
    fair_value_bear = float(valuation.fair_value_bear) if valuation.fair_value_bear is not None else None
    fair_value_bull = float(valuation.fair_value_bull) if valuation.fair_value_bull is not None else None
    fair_value_base = float(valuation.fair_value_base) if valuation.fair_value_base is not None else None
    fair_value_conservative = float(valuation.fair_value_conservative) if valuation.fair_value_conservative is not None else None

    net_margin = _latest_ratio_value(session, company.id, _NET_MARGIN_NAMES)
    roe = _latest_ratio_value(session, company.id, _ROE_NAMES)
    debt_to_equity = _latest_ratio_value(session, company.id, _DEBT_TO_EQUITY_NAMES)
    n_fundamental_inputs = sum(1 for v in (net_margin, roe, debt_to_equity) if v is not None)

    valuation_position = classify_valuation_position(current_price, fair_value_bear, fair_value_bull)
    fundamental_quality = classify_fundamental_quality(net_margin, roe, debt_to_equity)
    label = combine_recommendation(valuation_position, fundamental_quality)
    confidence = compute_confidence(
        float(valuation.data_quality_score) if valuation.data_quality_score is not None else None,
        n_fundamental_inputs,
    )

    sentiment_label, sentiment_score = _latest_sentiment(session, company.id)

    guardrails_triggered = []
    if valuation_position is None:
        guardrails_triggered.append("valuation_not_computable")
    if fundamental_quality is None:
        guardrails_triggered.append("fundamental_quality_not_computable")
    if debt_to_equity is not None and debt_to_equity > 2.0:
        guardrails_triggered.append("high_leverage")
    if sentiment_label in _NEGATIVE_SENTIMENT_LABELS:
        guardrails_triggered.append("recent_negative_sentiment")

    entry_zone = None
    if label in (LABEL_LAYAK_DIBELI, LABEL_AKUMULASI_BERTAHAP) and fair_value_conservative is not None and fair_value_base is not None:
        entry_zone = {"low": fair_value_conservative, "high": fair_value_base}
    elif label == LABEL_TUNGGU_HARGA and fair_value_conservative is not None and fair_value_bear is not None:
        entry_zone = {"low": fair_value_conservative, "high": fair_value_bear}

    scores = {
        "valuation_position": valuation_position,
        "fundamental_quality": fundamental_quality,
        "current_price": current_price,
        "fair_value_bear": fair_value_bear,
        "fair_value_base": fair_value_base,
        "fair_value_bull": fair_value_bull,
        "net_margin": net_margin,
        "roe": roe,
        "debt_to_equity": debt_to_equity,
        "ml_signal_used": False,  # explicit, not an omission -- see module docstring
        "sentiment_label": sentiment_label,
        "sentiment_score": sentiment_score,
        "sentiment_signal_used": sentiment_label is not None,  # False when this company has no scored news yet
    }

    session.execute(
        delete(RecommendationResult).where(
            RecommendationResult.company_id == company.id, RecommendationResult.as_of_date == as_of_date
        )
    )
    session.add(
        RecommendationResult(
            company_id=company.id,
            as_of_date=as_of_date,
            label=label,
            confidence=confidence,
            scores=scores,
            guardrails_triggered=guardrails_triggered or None,
            entry_zone=entry_zone,
            investment_style=None,  # not classified yet -- see docs/recommendation.md's "what's not built yet"
            suggested_horizon=_SUGGESTED_HORIZON,
        )
    )
    outcome.label = label
    outcome.confidence = confidence
    return outcome
