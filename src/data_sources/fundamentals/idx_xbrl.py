"""Adapter for officially downloaded IDX XBRL filing archives.

IDX's public website is protected by an access layer that currently
returns HTTP 403 to automated clients.  This adapter therefore does not
scrape or bypass it.  It ingests XBRL instance files obtained through an
authorized/manual IDX download together with a small JSON manifest that
records the exchange publication timestamp and original document URL.

The manifest is the boundary that keeps a real publication timestamp
separate from the conservative period-end-plus-lag estimate used by the
Yahoo fallback.  A minimal manifest looks like::

    {
      "filings": [{
        "ticker": "BBCA",
        "fiscal_period": "2025FY",
        "statement_type": "annual",
        "period_end": "2025-12-31",
        "published_at": "2026-01-23T17:42:00+07:00",
        "xbrl_file": "BBCA-2025FY.xbrl",
        "document_url": "https://www.idx.co.id/...",
        "filing_reference": "IDX-disclosure-id"
      }]
    }

``account_map`` may be supplied globally or per filing as
``{"RawTaxonomyLocalName": "standard_account_code"}``.  Unknown facts
are ignored, never guessed into an account.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from src.data_sources.base import (
    AccessType,
    ProviderUnavailableError,
    SourceDescriptor,
    SourcedValue,
    ValidationStatus,
)
from src.data_sources.fundamentals.base import FinancialStatementDocument, FundamentalsProvider
from src.data_sources.fundamentals.taxonomy import ACCOUNT_CODE_SECTIONS

_SOURCE = SourceDescriptor(
    name="idx_official_xbrl_archive",
    url="https://www.idx.co.id/id/perusahaan-tercatat/laporan-keuangan-dan-tahunan",
    access_type=AccessType.OFFICIAL,
)
_XBRLI = "http://www.xbrl.org/2003/instance"
_XSI = "http://www.w3.org/2001/XMLSchema-instance"


def _normalized_fact_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


_DEFAULT_FACT_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("Revenue", "SalesAndRevenue", "Revenues"),
    "cost_of_revenue": ("CostOfRevenue", "CostOfSales"),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncome", "ProfitFromOperations"),
    "operating_expense": ("OperatingExpenses",),
    "net_interest_income": ("NetInterestIncome",),
    "interest_income": ("InterestIncome",),
    "interest_expense": ("InterestExpense",),
    "ebitda": ("EBITDA",),
    "pretax_income": ("ProfitBeforeTax", "IncomeBeforeTax"),
    "tax_expense": ("IncomeTaxExpense", "TaxExpense"),
    "net_income": ("ProfitLoss", "NetIncome", "ProfitForThePeriod"),
    "eps_basic": ("BasicEarningsLossPerShare", "BasicEarningsPerShare"),
    "eps_diluted": ("DilutedEarningsLossPerShare", "DilutedEarningsPerShare"),
    "shares_basic": ("WeightedAverageNumberOfSharesOutstandingBasic",),
    "shares_diluted": ("WeightedAverageNumberOfDilutedSharesOutstanding",),
    "total_assets": ("Assets", "TotalAssets"),
    "total_liabilities": ("Liabilities", "TotalLiabilities"),
    "total_equity": ("Equity", "TotalEquity"),
    "current_assets": ("CurrentAssets", "AssetsCurrent"),
    "current_liabilities": ("CurrentLiabilities", "LiabilitiesCurrent"),
    "total_debt": ("Borrowings", "TotalDebt"),
    "cash_and_equivalents": ("CashAndCashEquivalents",),
    "shares_outstanding": ("NumberOfSharesOutstanding", "OrdinarySharesOutstanding"),
    "operating_cash_flow": ("NetCashFlowsFromOperatingActivities",),
    "investing_cash_flow": ("NetCashFlowsFromInvestingActivities",),
    "financing_cash_flow": ("NetCashFlowsFromFinancingActivities",),
    "free_cash_flow": ("FreeCashFlow",),
    "capital_expenditure": ("PaymentsToAcquirePropertyPlantAndEquipment", "CapitalExpenditure"),
    "dividends_paid": ("DividendsPaid",),
    "gross_loans": ("LoansGross", "GrossLoans"),
    "non_performing_loans_gross": ("NonPerformingLoansGross",),
    "non_performing_loans_net": ("NonPerformingLoansNet",),
    "earning_assets": ("AverageEarningAssets", "EarningAssets"),
    "regulatory_capital": ("RegulatoryCapital", "TotalRegulatoryCapital"),
    "risk_weighted_assets": ("RiskWeightedAssets",),
    "customer_deposits": ("CustomerDeposits", "DepositsFromCustomers"),
    "current_accounts": ("CurrentAccounts", "DemandDeposits"),
    "savings_accounts": ("SavingsAccounts", "SavingsDeposits"),
    "npl_gross_ratio_reported": ("GrossNonPerformingLoanRatio", "NPLGrossRatio"),
    "npl_net_ratio_reported": ("NetNonPerformingLoanRatio", "NPLNetRatio"),
    "net_interest_margin_reported": ("NetInterestMargin",),
    "capital_adequacy_ratio_reported": ("CapitalAdequacyRatio",),
    "proven_probable_reserves": ("ProvedAndProbableReserves", "ProvenAndProbableReserves"),
    "annual_production": ("AnnualProduction", "ProductionVolume"),
    "cash_cost_per_unit_reported": ("CashCostPerUnit",),
    "stripping_ratio_reported": ("StrippingRatio",),
}

_DEFAULT_NAME_TO_CODE = {
    _normalized_fact_name(alias): code
    for code, aliases in _DEFAULT_FACT_ALIASES.items()
    for alias in aliases
}


def _parse_datetime(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("published_at must include an explicit timezone")
    return parsed.astimezone(dt.UTC)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _context_dates(root: ET.Element) -> dict[str, dt.date]:
    dates: dict[str, dt.date] = {}
    for context in root.findall(f".//{{{_XBRLI}}}context"):
        context_id = context.get("id")
        if not context_id:
            continue
        instant = context.find(f".//{{{_XBRLI}}}instant")
        end_date = context.find(f".//{{{_XBRLI}}}endDate")
        raw = instant.text if instant is not None else (end_date.text if end_date is not None else None)
        if raw:
            try:
                dates[context_id] = dt.date.fromisoformat(raw.strip()[:10])
            except ValueError:
                continue
    return dates


def _numeric_value(element: ET.Element, multiplier: float) -> float | None:
    if element.get(f"{{{_XSI}}}nil", "false").casefold() == "true" or not element.text:
        return None
    raw = element.text.strip().replace(",", "")
    if raw.startswith("(") and raw.endswith(")"):
        raw = f"-{raw[1:-1]}"
    try:
        value = float(raw)
        inline_scale = int(element.get("scale", "0"))
        value = value * (10**inline_scale) * multiplier
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def parse_xbrl_facts(
    path: Path,
    period_end: dt.date,
    account_map: dict[str, str] | None = None,
    context_id: str | None = None,
    value_multiplier: float = 1.0,
) -> dict[str, float]:
    """Parse numeric facts for one reporting period from an XBRL instance."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ProviderUnavailableError(f"cannot read IDX XBRL instance {path}: {exc}") from exc

    mapped = dict(_DEFAULT_NAME_TO_CODE)
    for raw_name, code in (account_map or {}).items():
        if code not in ACCOUNT_CODE_SECTIONS:
            raise ProviderUnavailableError(f"unknown standard account code in account_map: {code}")
        mapped[_normalized_fact_name(raw_name)] = code

    contexts = _context_dates(root)
    facts: dict[str, float] = {}
    for element in root.iter():
        reference = element.get("contextRef")
        if not reference:
            continue
        if context_id is not None and reference != context_id:
            continue
        if context_id is None and contexts.get(reference) != period_end:
            continue

        raw_name = element.get("name") or _local_name(element.tag)
        if ":" in raw_name:
            raw_name = raw_name.split(":", 1)[1]
        account_code = mapped.get(_normalized_fact_name(raw_name))
        if not account_code or account_code in facts:
            continue
        value = _numeric_value(element, value_multiplier)
        if value is not None:
            facts[account_code] = value
    return facts


class IDXOfficialXBRLArchiveAdapter(FundamentalsProvider):
    """Read an authorized local archive of official IDX XBRL filings."""

    def __init__(self, manifest_path: str | Path) -> None:
        self._manifest_path = Path(manifest_path).expanduser().resolve()
        try:
            payload = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProviderUnavailableError(f"cannot read IDX XBRL manifest {self._manifest_path}: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("filings"), list):
            raise ProviderUnavailableError("IDX XBRL manifest must contain a filings array")
        self._global_account_map = payload.get("account_map", {})
        self._entries: dict[tuple[str, str], dict[str, Any]] = {}
        for entry in payload["filings"]:
            self._validate_entry(entry)
            key = (entry["ticker"].upper(), entry["fiscal_period"])
            self._entries[key] = entry

    @property
    def provider_name(self) -> str:
        return "idx_official_xbrl_archive"

    def _validate_entry(self, entry: Any) -> None:
        required = {
            "ticker",
            "fiscal_period",
            "statement_type",
            "period_end",
            "published_at",
            "xbrl_file",
            "document_url",
        }
        if not isinstance(entry, dict) or not required.issubset(entry):
            missing = sorted(required - set(entry if isinstance(entry, dict) else ()))
            raise ProviderUnavailableError(f"invalid IDX XBRL manifest entry; missing={missing}")
        if entry["statement_type"] not in {"annual", "quarterly"}:
            raise ProviderUnavailableError("statement_type must be annual or quarterly")
        period_end = dt.date.fromisoformat(entry["period_end"])
        published_at = _parse_datetime(entry["published_at"])
        if published_at.date() < period_end:
            raise ProviderUnavailableError("official published_at cannot precede period_end")
        self._resolve_xbrl_path(entry["xbrl_file"])

    def _resolve_xbrl_path(self, relative_path: str) -> Path:
        path = (self._manifest_path.parent / relative_path).resolve()
        if not path.is_relative_to(self._manifest_path.parent):
            raise ProviderUnavailableError("xbrl_file escapes the manifest directory")
        return path

    def list_available_statements(self, ticker: str, since: dt.date) -> SourcedValue[list[str]]:
        now = dt.datetime.now(dt.UTC)
        periods = sorted(
            period
            for (entry_ticker, period), entry in self._entries.items()
            if entry_ticker == ticker.upper() and _parse_datetime(entry["published_at"]).date() >= since
        )
        return SourcedValue(
            value=periods,
            source=_SOURCE,
            retrieved_at=now,
            available_at=now,
            period_start=since,
            period_end=None,
            validation_status=ValidationStatus.VALID if periods else ValidationStatus.INSUFFICIENT,
        )

    def get_statement(self, ticker: str, fiscal_period: str) -> SourcedValue[FinancialStatementDocument]:
        now = dt.datetime.now(dt.UTC)
        entry = self._entries.get((ticker.upper(), fiscal_period))
        if entry is None:
            return SourcedValue(
                value=None,
                source=_SOURCE,
                retrieved_at=now,
                available_at=now,
                period_start=None,
                period_end=None,
                validation_status=ValidationStatus.INSUFFICIENT,
            )

        period_end = dt.date.fromisoformat(entry["period_end"])
        account_map = {**self._global_account_map, **entry.get("account_map", {})}
        line_items = parse_xbrl_facts(
            self._resolve_xbrl_path(entry["xbrl_file"]),
            period_end,
            account_map=account_map,
            context_id=entry.get("context_id"),
            value_multiplier=float(entry.get("value_multiplier", 1.0)),
        )
        published_at = _parse_datetime(entry["published_at"])
        document = FinancialStatementDocument(
            company_ticker=ticker.upper(),
            statement_type=entry["statement_type"],
            fiscal_period=fiscal_period,
            source_format="xbrl",
            currency=entry.get("currency", "IDR"),
            scale=entry.get("scale", "unit"),
            line_items=line_items,
            auditor_opinion=entry.get("auditor_opinion"),
            going_concern_flag=bool(entry.get("going_concern_flag", False)),
            document_url=entry["document_url"],
            available_at_basis="official_idx_publication_timestamp",
            filing_reference=entry.get("filing_reference"),
            line_item_units=entry.get("account_units", {}),
        )
        return SourcedValue(
            value=document,
            source=_SOURCE,
            retrieved_at=now,
            available_at=published_at,
            period_start=None,
            period_end=period_end,
            validation_status=ValidationStatus.VALID if line_items else ValidationStatus.INSUFFICIENT,
        )
