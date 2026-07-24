"""Emiten metadata sync: provider -> ``companies`` (spec §5 step 2).

Deliberately minimal: writes only ``ticker`` and ``company_name``. Neither
adapter implemented so far (Twelve Data, Sectors.app) returns sector,
subsector, listing date, listing board, or free float in a bulk-friendly
way -- see ``CompanyRecord`` in ``src/data_sources/market/base.py`` for
why. Those fields stay ``NULL`` here rather than being guessed; a proper
"data master saham" source (spec §3.1 -- ideally IDX itself, or another
official registry) is needed before they can be filled in for real.

Never deletes or marks companies delisted based on a provider simply not
returning them in one call (spec §3.1: preserve delisted-company history
to avoid survivorship bias) -- this sync only adds new tickers and updates
the name of existing ones.
"""
from __future__ import annotations

import dataclasses

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.data_sources.base import ProviderUnavailableError
from src.data_sources.market.base import MarketDataProvider
from src.database.models.company import Company


@dataclasses.dataclass
class SyncOutcome:
    provider: str
    companies_seen: int = 0
    companies_created: int = 0
    companies_updated: int = 0
    skipped_reason: str | None = None


def sync_companies(session: Session, provider: MarketDataProvider) -> SyncOutcome:
    outcome = SyncOutcome(provider=provider.provider_name)

    try:
        result = provider.list_companies()
    except ProviderUnavailableError as exc:
        outcome.skipped_reason = f"provider unavailable: {exc}"
        return outcome

    if not result.is_usable():
        outcome.skipped_reason = f"provider returned no usable data (status={result.validation_status.value})"
        return outcome

    records = result.value
    outcome.companies_seen = len(records)
    if not records:
        return outcome

    existing = {c.ticker: c for c in session.scalars(select(Company))}

    for record in records:
        company = existing.get(record.ticker)
        if company is None:
            session.add(Company(ticker=record.ticker, company_name=record.company_name))
            outcome.companies_created += 1
        elif company.company_name != record.company_name:
            company.company_name = record.company_name
            outcome.companies_updated += 1

    return outcome
