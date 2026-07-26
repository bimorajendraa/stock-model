"""Company sector/subsector classification via Yahoo Finance (spec §3.1,
§3.5's real blocker). Real fix for a gap flagged repeatedly across this
project's docs: ``companies.sector_registry_id`` has been NULL for every
company since Tahap 1 because no adapter populated it -- market-data
adapters only ever returned ticker+name (`docs/data_sources.md`).

Verified live (2026-07-25): `yfinance`'s ``Ticker.get_info()`` returns
real GICS-style ``sector``/``industry`` fields for IDX tickers (e.g.
BBCA.JK -> sector="Financial Services", industry="Banks - Regional";
GOTO.JK -> sector="Technology", industry="Software - Infrastructure") --
same `research_only` status as every other Yahoo Finance data already
used in this project (OHLCV, fundamentals, market cap).

``SectorRegistry.metrics_config_key``/``valuation_config_key`` are
required (non-nullable) columns intended for a future config-driven
per-sector metrics/valuation system (spec §3.5/§10) that doesn't exist
yet -- populated here with the sector's own slug as a stable placeholder
key, not a fabricated distinct workflow. Documented, not hidden.

**Two real bugs found and fixed (2026-07-25), both live, both real DB
constraints** -- not caught by the code alone, only by actually running
this against every company:

1. ``sector_registry.sector_code`` has a real, global ``UNIQUE``
   constraint (not composite with ``subsector_code``) -- an early version
   of this module keyed rows on (sector_name, industry_name) but stored
   only ``slug(sector_name)`` as ``sector_code``, so the second industry
   within the same broad sector (e.g. "Financial Services" -> "Insurance
   - Property & Casualty" after "Banks - Regional" already existed) hit a
   real ``psycopg.errors.UniqueViolation`` mid-run.
2. ``sector_code`` is also ``VARCHAR(32)`` -- the first fix (concatenating
   sector+industry slugs) produced codes like
   ``financial_services_insurance_property_casualty`` (49 chars), which
   then hit a real ``psycopg.errors.StringDataRightTruncation``.

Fixed by deriving ``sector_code`` from a short, deterministic hash of the
full (sector, industry) pair -- guaranteed unique (collision-negligible)
and guaranteed to fit 32 chars, at the cost of not being human-readable
on its own. That's an acceptable trade: ``sector_name``/``subsector_name``
(``VARCHAR(128)``, plenty of room) are what any human-facing display
should read from, not ``sector_code``, which only needs to be a stable
machine key.
"""
from __future__ import annotations

import dataclasses
import hashlib
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.data_sources.market.yahoo_finance import default_yahoo_symbol
from src.database.models.company import Company, SectorRegistry

_SECTOR_CODE_MAX_LEN = 32
_SUBSECTOR_CODE_MAX_LEN = 32


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _sector_code(sector_name: str, subsector_name: str | None) -> str:
    """Deterministic, collision-safe, <=32-char code -- see module
    docstring's "two real bugs" note for why this isn't just a slug."""
    basis = f"{sector_name}|{subsector_name or ''}"
    digest = hashlib.sha256(basis.encode()).hexdigest()[:10]
    prefix_source = subsector_name or sector_name
    prefix_budget = _SECTOR_CODE_MAX_LEN - len(digest) - 1  # -1 for the separator
    prefix = _slug(prefix_source)[:prefix_budget]
    return f"{prefix}_{digest}"


@dataclasses.dataclass
class SectorClassificationOutcome:
    ticker: str
    sector: str | None = None
    industry: str | None = None
    skipped_reason: str | None = None


def _get_or_create_sector(session: Session, sector_name: str, subsector_name: str | None) -> SectorRegistry:
    subsector_code = _slug(subsector_name)[:_SUBSECTOR_CODE_MAX_LEN] if subsector_name else None
    sector_code = _sector_code(sector_name, subsector_name)
    existing = session.scalar(select(SectorRegistry).where(SectorRegistry.sector_code == sector_code))
    if existing is not None:
        return existing
    sector = SectorRegistry(
        sector_code=sector_code,
        sector_name=sector_name,
        subsector_code=subsector_code,
        subsector_name=subsector_name,
        metrics_config_key=sector_code,  # placeholder -- see module docstring
        valuation_config_key=sector_code,
    )
    session.add(sector)
    session.flush()
    return sector


def fetch_and_store_sector(session: Session, ticker: str) -> SectorClassificationOutcome:
    import yfinance as yf  # local import: keeps this optional dependency out of module-load path for callers that don't need it

    outcome = SectorClassificationOutcome(ticker=ticker)
    company = session.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        outcome.skipped_reason = "no matching Company row"
        return outcome

    try:
        info = yf.Ticker(default_yahoo_symbol(ticker)).get_info()
    except Exception as exc:  # noqa: BLE001 -- yfinance raises assorted transport/parsing exceptions
        outcome.skipped_reason = f"fetch failed: {exc}"
        return outcome

    sector_name = info.get("sector")
    industry_name = info.get("industry")
    if not sector_name:
        outcome.skipped_reason = "no sector data returned"
        return outcome

    sector = _get_or_create_sector(session, sector_name, industry_name)
    company.sector_registry_id = sector.id
    outcome.sector = sector_name
    outcome.industry = industry_name
    return outcome
