"""Validated, idempotent import of company name/ticker history."""

from __future__ import annotations

import csv
import dataclasses
import datetime as dt
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models.company import Company, CompanyAlias


@dataclasses.dataclass(frozen=True)
class CompanyAliasImportOutcome:
    rows_seen: int
    created: int
    updated: int


def _required_date(value: str, *, row_number: int) -> dt.date:
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"row {row_number}: effective_from must be an ISO date (YYYY-MM-DD)") from exc


def _optional_date(value: str | None, *, row_number: int) -> dt.date | None:
    if not value or not value.strip():
        return None
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"row {row_number}: effective_to must be an ISO date (YYYY-MM-DD)") from exc


def import_company_aliases(session: Session, csv_path: str | Path) -> CompanyAliasImportOutcome:
    """Import alias history from CSV without duplicating an existing identity.

    Required columns are ``ticker`` and ``effective_from``. At least one of
    ``previous_ticker`` and ``previous_name`` must be present on every row.
    Optional columns are ``effective_to`` and ``reason``.
    """

    path = Path(csv_path)
    if not path.is_file():
        raise ValueError(f"alias file does not exist: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        missing = {"ticker", "effective_from"} - fields
        if missing:
            raise ValueError(f"alias CSV missing required column(s): {', '.join(sorted(missing))}")
        rows = list(reader)

    companies = {company.ticker.upper(): company for company in session.scalars(select(Company))}
    existing_aliases = list(session.scalars(select(CompanyAlias)))
    existing = {
        (
            alias.company_id,
            (alias.previous_ticker or "").upper(),
            (alias.previous_name or "").casefold(),
            alias.effective_from,
        ): alias
        for alias in existing_aliases
    }

    created = 0
    updated = 0
    for row_number, row in enumerate(rows, start=2):
        ticker = (row.get("ticker") or "").strip().upper()
        company = companies.get(ticker)
        if company is None:
            raise ValueError(f"row {row_number}: unknown current company ticker {ticker!r}")

        previous_ticker = (row.get("previous_ticker") or "").strip().upper() or None
        previous_name = (row.get("previous_name") or "").strip() or None
        if previous_ticker is None and previous_name is None:
            raise ValueError(f"row {row_number}: previous_ticker or previous_name is required")
        if previous_ticker == company.ticker.upper():
            raise ValueError(f"row {row_number}: previous_ticker must differ from current ticker")

        effective_from = _required_date(row.get("effective_from") or "", row_number=row_number)
        effective_to = _optional_date(row.get("effective_to"), row_number=row_number)
        if effective_to is not None and effective_to < effective_from:
            raise ValueError(f"row {row_number}: effective_to cannot precede effective_from")
        reason = (row.get("reason") or "").strip() or None

        key = (
            company.id,
            (previous_ticker or "").upper(),
            (previous_name or "").casefold(),
            effective_from,
        )
        alias = existing.get(key)
        if alias is None:
            alias = CompanyAlias(
                company_id=company.id,
                previous_ticker=previous_ticker,
                previous_name=previous_name,
                effective_from=effective_from,
                effective_to=effective_to,
                reason=reason,
            )
            session.add(alias)
            existing[key] = alias
            created += 1
        elif alias.effective_to != effective_to or alias.reason != reason:
            alias.effective_to = effective_to
            alias.reason = reason
            updated += 1

    return CompanyAliasImportOutcome(rows_seen=len(rows), created=created, updated=updated)
