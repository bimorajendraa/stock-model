"""OHLCV, corporate actions, dividends (spec §3.2).

Raw vs. clean prices are separate tables on purpose (§3.2 rule: "Pisahkan
harga mentah dan harga yang sudah disesuaikan") -- ``market_prices_raw`` is
an append-only record of exactly what a provider returned;
``market_prices_clean`` holds validated, corporate-action-adjusted series
that features/models are allowed to read.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base
from src.database.models.mixins import SourceLineageMixin, TimestampMixin


class MarketPriceRaw(Base, TimestampMixin, SourceLineageMixin):
    __tablename__ = "market_prices_raw"
    __table_args__ = (UniqueConstraint("company_id", "trade_date", "source_id", name="uq_price_raw_company_date_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    trade_date: Mapped[dt.date] = mapped_column(nullable=False, index=True)

    open: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    high: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    low: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    close: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    volume: Mapped[int | None] = mapped_column(nullable=True)
    transaction_value: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    transaction_frequency: Mapped[int | None] = mapped_column(nullable=True)


class MarketPriceClean(Base, TimestampMixin, SourceLineageMixin):
    """Validated + corporate-action-adjusted. Derived from one or more raw
    rows (possibly cross-checked across providers) -- ``source_id`` here
    identifies the adjustment/validation pipeline run, not a single vendor."""

    __tablename__ = "market_prices_clean"
    __table_args__ = (UniqueConstraint("company_id", "trade_date", name="uq_price_clean_company_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    trade_date: Mapped[dt.date] = mapped_column(nullable=False, index=True)

    open: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    high: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    low: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    close: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    adjusted_close: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    volume: Mapped[int | None] = mapped_column(nullable=True)
    market_cap: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    adjustment_factor: Mapped[float | None] = mapped_column(Numeric(18, 8), nullable=True)

    is_outlier_flagged: Mapped[bool] = mapped_column(nullable=False, default=False)
    is_missing_trading_day_filled: Mapped[bool] = mapped_column(nullable=False, default=False)


class CorporateAction(Base, TimestampMixin, SourceLineageMixin):
    __tablename__ = "corporate_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # stock_split | reverse_split | rights_issue | bonus_shares | dividend | ticker_change | name_change
    announcement_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    ex_date: Mapped[dt.date | None] = mapped_column(nullable=True, index=True)
    ratio_or_value: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    details: Mapped[str | None] = mapped_column(String(512), nullable=True)


class Dividend(Base, TimestampMixin, SourceLineageMixin):
    __tablename__ = "dividends"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    dividend_type: Mapped[str] = mapped_column(String(16), nullable=False, default="cash")  # cash | stock
    announcement_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    cum_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    ex_date: Mapped[dt.date | None] = mapped_column(nullable=True, index=True)
    payment_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    amount_per_share: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    fiscal_period: Mapped[str | None] = mapped_column(String(16), nullable=True)
