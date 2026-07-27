"""Financial statement provider interface (spec §3.3).

Every returned statement must carry both ``period_end`` and
``available_at`` -- see SourcedValue -- because §3.3 forbids using a
statement before the date it was actually public, regardless of which
fiscal period it describes.
"""
from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod

from src.data_sources.base import SourcedValue


class FinancialStatementDocument:
    __slots__ = (
        "auditor_opinion",
        "available_at_basis",
        "company_ticker",
        "currency",
        "document_url",
        "filing_reference",
        "fiscal_period",
        "going_concern_flag",
        "line_item_units",
        "line_items",
        "scale",
        "source_format",
        "statement_type",
    )

    def __init__(
        self,
        company_ticker: str,
        statement_type: str,  # "quarterly" | "annual"
        fiscal_period: str,
        source_format: str,  # xbrl | json_csv_xlsx | html_table | pdf_text_layer | ocr
        currency: str,
        scale: str,
        line_items: dict[str, float | None],
        auditor_opinion: str | None = None,
        going_concern_flag: bool = False,
        document_url: str | None = None,
        available_at_basis: str | None = None,
        filing_reference: str | None = None,
        line_item_units: dict[str, str] | None = None,
    ) -> None:
        self.company_ticker = company_ticker
        self.statement_type = statement_type
        self.fiscal_period = fiscal_period
        self.source_format = source_format
        self.currency = currency
        self.scale = scale
        self.line_items = line_items
        self.auditor_opinion = auditor_opinion
        self.going_concern_flag = going_concern_flag
        self.document_url = document_url
        self.available_at_basis = available_at_basis
        self.filing_reference = filing_reference
        self.line_item_units = line_item_units or {}


class FundamentalsProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    def list_available_statements(
        self, ticker: str, since: dt.date
    ) -> SourcedValue[list[str]]:
        """Fiscal-period identifiers (e.g. "2026Q2") published for ``ticker``
        with an available_at on/after ``since``."""

    @abstractmethod
    def get_statement(
        self, ticker: str, fiscal_period: str
    ) -> SourcedValue[FinancialStatementDocument]:
        """One statement, in the highest-priority format available
        (xbrl > structured > html > pdf-text-layer > ocr, per spec §3.3)."""
