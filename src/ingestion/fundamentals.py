"""Fundamentals ingestion: provider adapter -> ``financial_statements_raw``
+ ``financial_statement_items`` (spec section 3.3, section 5 step 3-4
analogue for the fundamentals branch).

Same "assume company master data already exists" rule as
``ingestion/market_data.py``: a ticker with no matching ``Company`` row is
skipped, never auto-created.

No natural unique constraint exists on either fundamentals table (a
statement's real identity is company+statement_type+fiscal_period, but
that isn't enforced at the DB level yet) -- idempotency is handled the
same way as ``features/technical/pipeline.py``: clear every existing
statement (and its items) for the company, then rewrite from the
provider's current answer. Safe because the provider call itself is the
source of truth each time, not an incremental diff.
"""
from __future__ import annotations

import dataclasses
import datetime as dt

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.data_sources.base import ProviderUnavailableError, SourceDescriptor
from src.data_sources.fundamentals.base import FundamentalsProvider
from src.data_sources.fundamentals.taxonomy import ACCOUNT_CODE_SECTIONS
from src.database.models.company import Company
from src.database.models.fundamentals import FinancialStatementItem, FinancialStatementRaw
from src.database.models.mixins import QualityStatus
from src.database.models.ops import DataSourceRegistry
from src.ingestion.resilience import with_retry

_EARLIEST_SINCE = dt.date(2000, 1, 1)  # providers like yfinance only ever return recent years anyway

# Below this fraction of the 30-code taxonomy actually populated, a
# statement is real but too thin to be useful (observed live: the oldest
# column in a provider's rolling window, or a Q4 whose standalone figures
# aren't separately disclosed, commonly leaves only 1-3 items populated
# out of ~20-29 for a normal statement). Flagged INSUFFICIENT rather than
# silently kept alongside full statements at the same VALID status, and
# never dropped outright -- the few real numbers that DO exist are still
# real and still written, just clearly marked as incomplete.
_MIN_COMPLETENESS_RATIO = 0.2


@dataclasses.dataclass
class FundamentalsIngestOutcome:
    ticker: str
    provider: str
    statements_fetched: int = 0
    statements_written: int = 0
    items_written: int = 0
    skipped_reason: str | None = None


def _get_or_create_source(session: Session, descriptor: SourceDescriptor, category: str) -> DataSourceRegistry:
    source = session.scalar(select(DataSourceRegistry).where(DataSourceRegistry.name == descriptor.name))
    if source is not None:
        return source
    source = DataSourceRegistry(
        name=descriptor.name,
        category=category,
        access_type=descriptor.access_type.value,
        base_url=descriptor.url,
        is_active=True,
    )
    session.add(source)
    session.flush()
    return source


def ingest_fundamentals(
    session: Session,
    provider: FundamentalsProvider,
    ticker: str,
    ingestion_run_id: str,
    max_retries: int = 4,
) -> FundamentalsIngestOutcome:
    outcome = FundamentalsIngestOutcome(ticker=ticker, provider=provider.provider_name)

    company = session.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        outcome.skipped_reason = "no matching Company row -- run emiten metadata sync first"
        return outcome

    try:
        list_fetch = with_retry(max_retries)(provider.list_available_statements)
        listed = list_fetch(ticker, _EARLIEST_SINCE)
    except ProviderUnavailableError as exc:
        outcome.skipped_reason = f"provider unavailable: {exc}"
        return outcome

    if not listed.is_usable():
        outcome.skipped_reason = f"provider returned no available statements (status={listed.validation_status.value})"
        return outcome

    fiscal_periods = listed.value
    outcome.statements_fetched = len(fiscal_periods)
    if not fiscal_periods:
        return outcome

    documents = []
    for fiscal_period in fiscal_periods:
        try:
            fetch = with_retry(max_retries)(provider.get_statement)
            result = fetch(ticker, fiscal_period)
        except ProviderUnavailableError:
            continue
        if result.is_usable():
            documents.append(result)

    if not documents:
        outcome.skipped_reason = "no usable statements after fetching each fiscal period"
        return outcome

    source = _get_or_create_source(session, documents[0].source, category="fundamentals")

    existing_ids = session.scalars(
        select(FinancialStatementRaw.id).where(FinancialStatementRaw.company_id == company.id)
    ).all()
    if existing_ids:
        session.execute(delete(FinancialStatementItem).where(FinancialStatementItem.statement_id.in_(existing_ids)))
        session.execute(delete(FinancialStatementRaw).where(FinancialStatementRaw.company_id == company.id))

    for result in documents:
        doc = result.value
        completeness = len(doc.line_items) / len(ACCOUNT_CODE_SECTIONS)
        quality_status = QualityStatus.VALID if completeness >= _MIN_COMPLETENESS_RATIO else QualityStatus.INSUFFICIENT

        raw = FinancialStatementRaw(
            company_id=company.id,
            statement_type=doc.statement_type,
            fiscal_period=doc.fiscal_period,
            source_format=doc.source_format,
            auditor_opinion=doc.auditor_opinion,
            going_concern_flag=doc.going_concern_flag,
            statement_currency=doc.currency,
            scale=doc.scale,
            document_url=doc.document_url,
            source_id=source.id,
            retrieved_at=result.retrieved_at,
            available_at=result.available_at,
            period_start=result.period_start,
            period_end=result.period_end,
            currency=doc.currency,
            unit=doc.scale,
            is_restated=False,
            quality_status=quality_status,
            raw_payload={
                "available_at_basis": f"estimated_period_end_plus_lag ({provider.provider_name})",
                "n_items": len(doc.line_items),
                "completeness_ratio": round(completeness, 4),
            },
        )
        session.add(raw)
        session.flush()  # assign raw.id for the items below

        for account_code, value in doc.line_items.items():
            section = ACCOUNT_CODE_SECTIONS[account_code]
            session.add(
                FinancialStatementItem(
                    statement_id=raw.id,
                    company_id=company.id,
                    statement_section=section,
                    account_code=account_code,
                    account_name_reported=account_code,
                    value=value,
                    source_id=source.id,
                    retrieved_at=result.retrieved_at,
                    available_at=result.available_at,
                    period_start=result.period_start,
                    period_end=result.period_end,
                    currency=doc.currency,
                    unit=doc.scale,
                    is_restated=False,
                    quality_status=quality_status,
                )
            )
            outcome.items_written += 1
        outcome.statements_written += 1

    return outcome
