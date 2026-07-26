"""financial_statement_items -> financial_ratios (spec section 8).

Only statements with ``quality_status != INSUFFICIENT`` are used -- a
statement already flagged too thin to trust (see
``docs/fundamentals.md``'s completeness-based quality_status section)
shouldn't feed a ratio that then *looks* confidently computed.

Price-dependent ratios (P/E, P/B) look up the company's own
``market_prices_clean`` close on/before the statement's ``available_at``
date -- never a later price, which would be exactly the point-in-time
leakage this project forbids elsewhere (spec section 3.3/17).

``ratio_name`` is suffixed with the statement type
(``net_margin__annual`` vs. ``net_margin__quarterly``) because an annual
and its Q4 quarterly statement commonly share the same ``period_end``
(both end 2025-12-31, say) and ``financial_ratios`` has no separate
statement_type column of its own -- without the suffix, two ratios from
two different reporting granularities would collide on
(company_id, ratio_name, period_end).

Every ratio the taxonomy defines is written per statement, applicable or
not (``is_applicable=False`` with ``value=None`` when a bank has no
computable ``current_ratio``, for instance) -- ``FinancialRatio`` was
designed for exactly this distinction, not for silently omitting rows.
"""
from __future__ import annotations

import dataclasses
import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.data_sources.base import AccessType, SourceDescriptor
from src.database.models.company import Company
from src.database.models.fundamentals import FinancialRatio, FinancialStatementItem, FinancialStatementRaw
from src.database.models.market import MarketPriceClean
from src.database.models.mixins import QualityStatus
from src.database.models.ops import DataSourceRegistry
from src.features.fundamentals.ratios import compute_all_ratios

RATIO_VERSION = "v1"

_INTERNAL_SOURCE = SourceDescriptor(
    name="internal_fundamental_ratios",
    url="internal://features/fundamentals/pipeline",
    access_type=AccessType.INTERNAL_DERIVED,
)


@dataclasses.dataclass
class FundamentalRatioOutcome:
    ticker: str
    statements_processed: int = 0
    ratios_written: int = 0
    skipped_reason: str | None = None


def _get_or_create_internal_source(session: Session) -> DataSourceRegistry:
    source = session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == _INTERNAL_SOURCE.name))
    if source is not None:
        return source
    source = DataSourceRegistry(
        name=_INTERNAL_SOURCE.name,
        category="fundamentals",
        access_type=_INTERNAL_SOURCE.access_type.value,
        base_url=_INTERNAL_SOURCE.url,
        is_active=True,
    )
    session.add(source)
    session.flush()
    return source


def _price_as_of(session: Session, company_id: int, as_of: dt.date) -> float | None:
    price = session.scalar(
        select(MarketPriceClean.close)
        .where(
            MarketPriceClean.company_id == company_id,
            MarketPriceClean.trade_date <= as_of,
            MarketPriceClean.close.is_not(None),
        )
        .order_by(MarketPriceClean.trade_date.desc())
    )
    return float(price) if price is not None else None


def compute_fundamental_ratios(session: Session, ticker: str) -> FundamentalRatioOutcome:
    outcome = FundamentalRatioOutcome(ticker=ticker)

    company = session.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        outcome.skipped_reason = "no matching Company row"
        return outcome

    statements = list(
        session.scalars(
            select(FinancialStatementRaw)
            .where(
                FinancialStatementRaw.company_id == company.id,
                FinancialStatementRaw.quality_status != QualityStatus.INSUFFICIENT,
            )
            .order_by(FinancialStatementRaw.period_end)
        )
    )
    if not statements:
        outcome.skipped_reason = "no usable (non-INSUFFICIENT) statements -- run fundamentals sync first"
        return outcome

    source = _get_or_create_internal_source(session)
    now = dt.datetime.now(dt.UTC)

    # No natural unique constraint on financial_ratios (same Tahap 1
    # long-format-table situation as technical_features/
    # financial_statement_items) -- clear this company's rows first so
    # recomputation is idempotent rather than duplicating.
    session.query(FinancialRatio).filter(FinancialRatio.company_id == company.id).delete()

    rows = []
    for statement in statements:
        items_query = session.scalars(
            select(FinancialStatementItem).where(FinancialStatementItem.statement_id == statement.id)
        )
        items = {item.account_code: float(item.value) for item in items_query if item.value is not None}

        price = _price_as_of(session, company.id, statement.available_at.date())
        ratios = compute_all_ratios(items, price)

        for ratio_name, value in ratios.items():
            rows.append(
                FinancialRatio(
                    company_id=company.id,
                    ratio_name=f"{ratio_name}__{statement.statement_type}",
                    value=value,
                    is_applicable=value is not None,
                    computation_version=RATIO_VERSION,
                    source_id=source.id,
                    retrieved_at=now,
                    available_at=statement.available_at,
                    period_start=statement.period_start,
                    period_end=statement.period_end,
                    currency=statement.currency,
                    unit=statement.unit,
                    is_restated=False,
                    quality_status=QualityStatus.VALID,
                )
            )
        outcome.statements_processed += 1

    session.add_all(rows)
    outcome.ratios_written = len(rows)
    return outcome
