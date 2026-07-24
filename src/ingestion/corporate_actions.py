"""Corporate action ingestion: provider -> ``corporate_actions`` (spec
section 6).

Every source's report of an event is its own row, keyed by (company,
action_type, ex_date, source_provider) -- re-running ingestion for the
same source updates that source's row (idempotent), but two different
providers reporting the same real-world event never overwrite each other
(spec: "Jangan menghapus salah satu versi ketika terjadi konflik"). No row
here is ever marked ``officially_verified`` by ingestion itself -- that
only happens through a separate confirmation step against an official
source, not yet implemented.
"""
from __future__ import annotations

import dataclasses
import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.data_sources.base import ProviderUnavailableError
from src.data_sources.market.base import MarketDataProvider
from src.database.models.company import Company
from src.database.models.market import CorporateAction
from src.database.models.mixins import QualityStatus
from src.ingestion.market_data import _get_or_create_source
from src.ingestion.resilience import with_retry


@dataclasses.dataclass
class CorporateActionIngestOutcome:
    ticker: str
    provider: str
    records_fetched: int = 0
    records_written: int = 0
    skipped_reason: str | None = None


def ingest_corporate_actions(
    session: Session,
    provider: MarketDataProvider,
    ticker: str,
    start: dt.date,
    end: dt.date,
    max_retries: int = 4,
) -> CorporateActionIngestOutcome:
    outcome = CorporateActionIngestOutcome(ticker=ticker, provider=provider.provider_name)

    company = session.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        outcome.skipped_reason = "no matching Company row -- run emiten metadata sync first"
        return outcome

    try:
        fetch = with_retry(max_retries)(provider.get_corporate_actions)
        result = fetch(ticker, start, end)
    except ProviderUnavailableError as exc:
        outcome.skipped_reason = f"provider unavailable: {exc}"
        return outcome

    if not result.is_usable():
        outcome.skipped_reason = f"provider returned no usable data (status={result.validation_status.value})"
        return outcome

    actions = result.value
    outcome.records_fetched = len(actions)
    if not actions:
        return outcome

    source = _get_or_create_source(session, result.source, category="market")

    written = 0
    for action in actions:
        action_type = action["action_type"]
        ex_date_str = action.get("ex_date")
        ex_date = dt.date.fromisoformat(ex_date_str) if ex_date_str else None

        existing = session.scalar(
            select(CorporateAction).where(
                CorporateAction.company_id == company.id,
                CorporateAction.action_type == action_type,
                CorporateAction.ex_date == ex_date,
                CorporateAction.source_provider == provider.provider_name,
            )
        )

        fields = {
            "company_id": company.id,
            "action_type": action_type,
            "ex_date": ex_date,
            "cash_amount": action.get("cash_amount"),
            "split_from": action.get("split_from"),
            "split_to": action.get("split_to"),
            "source_provider": provider.provider_name,
            "verification_status": action.get("verification_status", "provider_reported"),
            "source_id": source.id,
            "retrieved_at": result.retrieved_at,
            "available_at": result.available_at,
            "period_start": start,
            "period_end": end,
            "currency": "IDR",
            "unit": "unit",
            "is_restated": False,
            "quality_status": QualityStatus.VALID,
        }

        if existing is not None:
            for key, value in fields.items():
                setattr(existing, key, value)
        else:
            session.add(CorporateAction(**fields))
        written += 1

    outcome.records_written = written
    return outcome
