"""Emiten metadata sync: provider -> ``companies`` (spec §5 step 2).

Deliberately minimal: writes ``ticker``, ``company_name``, and normalized
``asset_type``. Asset type prevents provider-returned indices/ETFs from
entering equity pipelines; it is taken from provider metadata when present
and conservatively inferred from explicit Index/ETF names otherwise. Neither
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
from src.data_sources.market.base import CompanyRecord, MarketDataProvider
from src.database.models.company import AssetType, Company

_PROVIDER_ASSET_TYPES = {
    "common stock": AssetType.EQUITY.value,
    "equity": AssetType.EQUITY.value,
    "stock": AssetType.EQUITY.value,
    "index": AssetType.INDEX.value,
    "exchange traded fund": AssetType.ETF.value,
    "etf": AssetType.ETF.value,
}


def infer_asset_type(record: CompanyRecord) -> str:
    """Normalize provider metadata, with a conservative name fallback."""
    raw_type = (record.asset_type or "").strip().casefold()
    if raw_type in _PROVIDER_ASSET_TYPES:
        return _PROVIDER_ASSET_TYPES[raw_type]

    normalized_name = record.company_name.strip().casefold()
    if normalized_name.endswith(" index"):
        return AssetType.INDEX.value
    if normalized_name.endswith(" etf") or "exchange traded fund" in normalized_name:
        return AssetType.ETF.value
    if raw_type:
        return AssetType.OTHER.value
    return AssetType.EQUITY.value


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
        asset_type = infer_asset_type(record)
        company = existing.get(record.ticker)
        if company is None:
            session.add(
                Company(
                    ticker=record.ticker,
                    company_name=record.company_name,
                    asset_type=asset_type,
                )
            )
            outcome.companies_created += 1
        else:
            changed = False
            if company.company_name != record.company_name:
                company.company_name = record.company_name
                changed = True
            if company.asset_type != asset_type:
                company.asset_type = asset_type
                changed = True
            if changed:
                outcome.companies_updated += 1

    return outcome
