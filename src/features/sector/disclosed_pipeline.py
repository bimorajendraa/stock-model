"""Official filing facts -> per-company sector-specific metrics."""
from __future__ import annotations

import dataclasses

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models.company import Company
from src.database.models.fundamentals import FinancialStatementItem, FinancialStatementRaw
from src.database.models.sector import SectorSpecificMetric
from src.features.sector.disclosed import compute_bank_metrics, compute_mining_metrics

_WRITTEN_METRICS = {
    "npl_gross_pct",
    "npl_net_pct",
    "net_interest_margin_pct",
    "capital_adequacy_ratio_pct",
    "loan_to_deposit_ratio_pct",
    "casa_ratio_pct",
    "reserve_life_years",
    "cash_cost_per_unit",
    "stripping_ratio",
    "proven_probable_reserves",
    "annual_production",
}
_BANK_FACTS = {
    "gross_loans",
    "non_performing_loans_gross",
    "non_performing_loans_net",
    "earning_assets",
    "net_interest_income",
    "regulatory_capital",
    "risk_weighted_assets",
    "customer_deposits",
    "current_accounts",
    "savings_accounts",
    "npl_gross_ratio_reported",
    "npl_net_ratio_reported",
    "net_interest_margin_reported",
    "capital_adequacy_ratio_reported",
}
_MINING_FACTS = {
    "proven_probable_reserves",
    "annual_production",
    "cash_cost_per_unit_reported",
    "stripping_ratio_reported",
}


@dataclasses.dataclass
class DisclosedMetricsOutcome:
    ticker: str
    metrics_written: int = 0
    skipped_reason: str | None = None


def _items(session: Session, statement_id: int) -> tuple[dict[str, float], dict[str, str]]:
    rows = session.execute(
        select(FinancialStatementItem.account_code, FinancialStatementItem.value, FinancialStatementItem.unit).where(
            FinancialStatementItem.statement_id == statement_id
        )
    ).all()
    values = {code: float(value) for code, value, _unit in rows if value is not None}
    units = {code: unit for code, value, unit in rows if value is not None and unit}
    return values, units


def compute_disclosed_sector_metrics(session: Session, ticker: str) -> DisclosedMetricsOutcome:
    outcome = DisclosedMetricsOutcome(ticker=ticker)
    company = session.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        outcome.skipped_reason = "no matching Company row"
        return outcome
    if company.sector_registry_id is None or company.sector is None:
        outcome.skipped_reason = "company has no sector classification"
        return outcome

    statements = list(
        session.scalars(
            select(FinancialStatementRaw)
            .where(FinancialStatementRaw.company_id == company.id)
            .order_by(FinancialStatementRaw.available_at.desc())
        )
    )
    if not statements:
        outcome.skipped_reason = "company has no financial statements"
        return outcome

    classification = f"{company.sector.sector_name} {company.sector.subsector_name or ''}".casefold()
    if "bank" in classification:
        relevant_facts = _BANK_FACTS
        formula = "bank"
    elif any(word in classification for word in ("mining", "coal", "gold", "oil & gas e&p")):
        relevant_facts = _MINING_FACTS
        formula = "mining"
    else:
        outcome.skipped_reason = "no disclosed-metric formula configured for this sector"
        return outcome

    statement_items: dict[int, tuple[dict[str, float], dict[str, str]]] = {}
    current = None
    for statement in statements:
        values_and_units = _items(session, statement.id)
        statement_items[statement.id] = values_and_units
        if relevant_facts.intersection(values_and_units[0]):
            current = statement
            break
    if current is None:
        outcome.skipped_reason = "no filing contains usable sector-specific disclosed facts"
        return outcome

    previous = None
    for row in statements:
        if (
            row.statement_type != current.statement_type
            or row.period_end is None
            or current.period_end is None
            or row.period_end >= current.period_end
        ):
            continue
        values_and_units = statement_items.get(row.id) or _items(session, row.id)
        statement_items[row.id] = values_and_units
        if relevant_facts.intersection(values_and_units[0]):
            previous = row
            break
    current_values, current_units = statement_items[current.id]
    previous_values = _items(session, previous.id)[0] if previous else {}

    if formula == "bank":
        metrics = compute_bank_metrics(
            current_values,
            previous_values,
            annual=current.statement_type == "annual",
        )
    else:
        metrics = compute_mining_metrics(current_values, current_units)

    session.query(SectorSpecificMetric).filter(
        SectorSpecificMetric.company_id == company.id,
        SectorSpecificMetric.metric_name.in_(_WRITTEN_METRICS),
    ).delete(synchronize_session=False)
    if not metrics:
        outcome.skipped_reason = "latest filing has no usable sector-specific disclosed facts"
        return outcome

    rows = [
        SectorSpecificMetric(
            company_id=company.id,
            sector_registry_id=company.sector_registry_id,
            metric_name=name,
            value=value,
            source_id=current.source_id,
            retrieved_at=current.retrieved_at,
            available_at=current.available_at,
            period_start=current.period_start,
            period_end=current.period_end,
            currency=current.currency,
            unit=unit,
            is_restated=current.is_restated,
            quality_status=current.quality_status,
            raw_payload={
                "calculation": "deterministic_from_disclosed_filing_facts",
                "statement_id": current.id,
                "source_format": current.source_format,
            },
        )
        for name, (value, unit) in metrics.items()
    ]
    session.add_all(rows)
    outcome.metrics_written = len(rows)
    return outcome
