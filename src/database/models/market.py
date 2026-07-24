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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base
from src.database.models.mixins import SourceLineageMixin, TimestampMixin


class MarketPriceRaw(Base, TimestampMixin, SourceLineageMixin):
    __tablename__ = "market_prices_raw"
    __table_args__ = (UniqueConstraint("company_id", "trade_date", "source_id", name="uq_price_raw_company_date_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    trade_date: Mapped[dt.date] = mapped_column(nullable=False, index=True)

    # Always raw -- never overwritten with an adjusted value (spec: "Jangan
    # kehilangan harga mentah karena seluruh proses adjustment dilakukan
    # otomatis oleh library").
    open: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    high: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    low: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    close: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    volume: Mapped[int | None] = mapped_column(nullable=True)
    transaction_value: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    transaction_frequency: Mapped[int | None] = mapped_column(nullable=True)

    # Provider's own adjusted close (e.g. yfinance "Adj Close"), kept
    # strictly separate from the raw `close` above.
    adjusted_close_provider: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    provider_adjustment_status: Mapped[str | None] = mapped_column(String(48), nullable=True)

    provider_symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    exchange: Mapped[str | None] = mapped_column(String(16), nullable=True)
    interval: Mapped[str] = mapped_column(String(16), nullable=False, default="1day")

    usage_restriction: Mapped[str] = mapped_column(String(24), nullable=False, default="unspecified")
    # research_only | licensed | unspecified
    verification_status: Mapped[str] = mapped_column(String(24), nullable=False, default="provider_reported")
    # provider_reported | reconciled_matched | reconciled_mismatch
    adjustment_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ingestion_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


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
    """Multi-provider, provisional-until-verified corporate action log.

    Distinct from ``dividends`` (Tahap 1): that table is for confirmed
    per-share dividend records used by fundamental/valuation calculations.
    This table is the raw, multi-source ingestion log -- a Yahoo Finance
    row and a Sectors.app row for the same real-world event both land here
    as separate rows (never overwriting each other, per spec: "Jangan
    menghapus salah satu versi ketika terjadi konflik"), and
    ``verification_status`` tracks how much to trust any one of them.
    """

    __tablename__ = "corporate_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # cash_dividend | stock_dividend | stock_split | reverse_split |
    # rights_issue | bonus_share | ticker_change | merger | spin_off

    announcement_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    cum_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    ex_date: Mapped[dt.date | None] = mapped_column(nullable=True, index=True)
    record_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    payment_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    effective_date: Mapped[dt.date | None] = mapped_column(nullable=True)

    cash_amount: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)  # per-share, dividends
    ratio_or_value: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)  # generic (e.g. rights ratio)
    split_from: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    split_to: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    details: Mapped[str | None] = mapped_column(String(512), nullable=True)

    source_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    verification_status: Mapped[str] = mapped_column(String(24), nullable=False, default="provider_reported")
    # provider_reported | single_source | officially_verified | source_conflict | rejected
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)


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


class CompanyProviderSymbol(Base, TimestampMixin):
    """Provider-specific ticker mapping (e.g. BBCA -> BBCA.JK on Yahoo
    Finance), kept out of ``companies.ticker`` entirely -- the canonical
    ticker never changes to accommodate a vendor's symbol convention."""

    __tablename__ = "company_provider_symbols"
    __table_args__ = (UniqueConstraint("company_id", "provider", name="uq_company_provider"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(16), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    verified_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)


class MarketPriceQuarantine(Base, TimestampMixin):
    """Bars that failed OHLCV validation land here instead of being
    silently dropped or written to ``market_prices_raw`` -- spec: "Jangan
    langsung menghapus bar yang gagal."""

    __tablename__ = "market_price_quarantine"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    trade_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    raw_row: Mapped[dict] = mapped_column(JSONB, nullable=False)
    validation_errors: Mapped[list] = mapped_column(JSONB, nullable=False)
    ingestion_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    found_at: Mapped[dt.datetime] = mapped_column(nullable=False)
    resolved: Mapped[bool] = mapped_column(nullable=False, default=False)


class MarketDataReconciliation(Base, TimestampMixin):
    """Comparison of a primary provider's close/volume against a
    verification source (ideally IDX itself) for a given trading date."""

    __tablename__ = "market_data_reconciliation"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    trading_date: Mapped[dt.date] = mapped_column(nullable=False, index=True)
    primary_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    verification_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    primary_close: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    verification_close: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    absolute_difference: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    percentage_difference: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    volume_difference: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    # matched | within_tolerance | mismatch | verification_unavailable
    checked_at: Mapped[dt.datetime] = mapped_column(nullable=False)
