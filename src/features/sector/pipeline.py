"""financial_ratios -> sector_specific_metrics (spec section 3.5/8), via
the percentile-rank logic in ``relative.py``.

Computed **per sector** (needs the whole real peer group at once), unlike
every other pipeline in this project which is computed per company --
call ``compute_sector_relative_metrics`` once per ``sector_registry_id``,
not once per ticker.

Only ``is_applicable`` ratio values participate in a peer group -- a
bank's not-applicable ``current_ratio`` must not be treated as "0" and
skew everyone else's percentile.
"""
from __future__ import annotations

import dataclasses
import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.data_sources.base import AccessType, SourceDescriptor
from src.database.models.company import Company, SectorRegistry
from src.database.models.fundamentals import FinancialRatio
from src.database.models.mixins import QualityStatus
from src.database.models.ops import DataSourceRegistry
from src.database.models.sector import SectorSpecificMetric
from src.features.sector.relative import percentile_rank

METRIC_VERSION = "v1"

# ratio_name base (financial_ratios strips the __annual/__quarterly
# suffix here -- most recent value regardless of statement granularity,
# same convention as src/valuation/pipeline.py and
# src/recommendation/pipeline.py)
_RATIO_NAMES = {
    "net_margin": ("net_margin__annual", "net_margin__quarterly"),
    "roe": ("roe__annual", "roe__quarterly"),
    "debt_to_equity": ("debt_to_equity__annual", "debt_to_equity__quarterly"),
}

_INTERNAL_SOURCE = SourceDescriptor(
    name="internal_sector_relative_metrics",
    url="internal://features/sector/pipeline",
    access_type=AccessType.INTERNAL_DERIVED,
)


@dataclasses.dataclass
class SectorRelativeOutcome:
    sector_registry_id: int
    sector_name: str | None = None
    companies_considered: int = 0
    metrics_written: int = 0
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


def compute_sector_relative_metrics(session: Session, sector_registry_id: int) -> SectorRelativeOutcome:
    outcome = SectorRelativeOutcome(sector_registry_id=sector_registry_id)

    sector = session.get(SectorRegistry, sector_registry_id)
    if sector is None:
        outcome.skipped_reason = "no matching SectorRegistry row"
        return outcome
    outcome.sector_name = sector.sector_name

    companies = list(session.scalars(select(Company).where(Company.sector_registry_id == sector_registry_id)))
    outcome.companies_considered = len(companies)
    if not companies:
        outcome.skipped_reason = "no companies classified into this sector"
        return outcome

    # metric_name -> {company_id: value} for companies with a real,
    # applicable value -- the peer group for that metric specifically
    # (a company missing one ratio can still be ranked on the others).
    values_by_metric: dict[str, dict[int, float]] = {name: {} for name in _RATIO_NAMES}
    for company in companies:
        for metric_name, ratio_names in _RATIO_NAMES.items():
            value = _latest_ratio_value(session, company.id, ratio_names)
            if value is not None:
                values_by_metric[metric_name][company.id] = value

    source = _get_or_create_internal_source(session)
    now = dt.datetime.now(dt.UTC)

    company_ids = [c.id for c in companies]
    session.query(SectorSpecificMetric).filter(
        SectorSpecificMetric.sector_registry_id == sector_registry_id,
        SectorSpecificMetric.company_id.in_(company_ids),
        SectorSpecificMetric.metric_name.like("%_percentile_in_sector"),
    ).delete(synchronize_session=False)

    rows = []
    for metric_name, values_by_company in values_by_metric.items():
        peer_values = list(values_by_company.values())
        for company_id, value in values_by_company.items():
            rank = percentile_rank(value, peer_values)
            if rank is None:
                continue
            rows.append(
                SectorSpecificMetric(
                    company_id=company_id,
                    sector_registry_id=sector_registry_id,
                    metric_name=f"{metric_name}_percentile_in_sector",
                    value=rank,
                    source_id=source.id,
                    retrieved_at=now,
                    available_at=now,
                    currency="IDR",
                    unit="percentile",
                    is_restated=False,
                    quality_status=QualityStatus.VALID,
                )
            )

    session.add_all(rows)
    outcome.metrics_written = len(rows)
    return outcome
