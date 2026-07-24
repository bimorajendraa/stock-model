"""Financial statements and derived ratios (spec §3.3, §8).

``period_end`` and ``available_at`` (from SourceLineageMixin) are the two
dates the spec insists must never be conflated: a Q2 statement can cover
period_end=2026-06-30 but not be public until available_at=2026-07-28.
Every downstream feature/model/backtest must filter on available_at, never
period_end.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base
from src.database.models.mixins import SourceLineageMixin, TimestampMixin


class FinancialStatementRaw(Base, TimestampMixin, SourceLineageMixin):
    """One row per filed document (a quarterly or annual report)."""

    __tablename__ = "financial_statements_raw"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    statement_type: Mapped[str] = mapped_column(String(16), nullable=False)  # quarterly | annual
    fiscal_period: Mapped[str] = mapped_column(String(16), nullable=False)  # e.g. "2026Q2", "2025FY"

    source_format: Mapped[str] = mapped_column(String(16), nullable=False)
    # xbrl | json_csv_xlsx | html_table | pdf_text_layer | ocr  (priority order per spec §3.3)

    auditor_opinion: Mapped[str | None] = mapped_column(String(64), nullable=True)
    going_concern_flag: Mapped[bool] = mapped_column(nullable=False, default=False)
    statement_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    scale: Mapped[str] = mapped_column(String(16), nullable=False, default="unit")  # thousand | million | billion | unit
    document_url: Mapped[str | None] = mapped_column(Text, nullable=True)


class FinancialStatementItem(Base, TimestampMixin, SourceLineageMixin):
    """One standardized line item extracted from a filed statement."""

    __tablename__ = "financial_statement_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    statement_id: Mapped[int] = mapped_column(ForeignKey("financial_statements_raw.id"), nullable=False, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)

    statement_section: Mapped[str] = mapped_column(String(32), nullable=False)
    # balance_sheet | income_statement | cash_flow | equity_changes | notes

    account_code: Mapped[str] = mapped_column(String(64), nullable=False)  # standardized taxonomy code
    account_name_reported: Mapped[str] = mapped_column(String(256), nullable=False)
    value: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)


class FinancialRatio(Base, TimestampMixin, SourceLineageMixin):
    """Deterministically computed ratios (never LLM-computed, spec §2.15)."""

    __tablename__ = "financial_ratios"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    ratio_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    value: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    is_applicable: Mapped[bool] = mapped_column(nullable=False, default=True)
    # False => "not_applicable" per spec §8 valuation section, not zero
    computation_version: Mapped[str] = mapped_column(String(32), nullable=False)
