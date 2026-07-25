"""Master data: companies, aliases/ticker history, sector registry (spec §3.1)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base
from src.database.models.mixins import TimestampMixin


class SectorRegistry(Base, TimestampMixin):
    """Sector/subsector taxonomy, and the config key used to select which
    sector-specific metrics (§3.5) and valuation methods (§10) apply."""

    __tablename__ = "sector_registry"

    id: Mapped[int] = mapped_column(primary_key=True)
    sector_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    sector_name: Mapped[str] = mapped_column(String(128), nullable=False)
    subsector_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subsector_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metrics_config_key: Mapped[str] = mapped_column(String(64), nullable=False)
    valuation_config_key: Mapped[str] = mapped_column(String(64), nullable=False)


class Company(Base, TimestampMixin):
    """One row per IDX-listed issuer (current identity)."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    company_name: Mapped[str] = mapped_column(String(256), nullable=False)
    sector_registry_id: Mapped[int | None] = mapped_column(ForeignKey("sector_registry.id"), nullable=True)

    listing_board: Mapped[str | None] = mapped_column(String(32), nullable=True)  # papan pencatatan
    listing_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    ipo_flag_limited_history: Mapped[bool] = mapped_column(nullable=False, default=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    # active | suspended | delisted

    delisting_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    # BigInteger, not the 32-bit default: real IDX share counts exceed
    # 2^31 (BBCA alone has ~122.9 billion shares outstanding) -- hit live
    # via a real psycopg.errors.NumericValueOutOfRange while testing this
    # feature, same bug class as market_prices_raw.volume earlier.
    shares_outstanding: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    free_float_pct: Mapped[float | None] = mapped_column(nullable=True)

    sector = relationship("SectorRegistry")
    aliases = relationship("CompanyAlias", back_populates="company")


class CompanyAlias(Base, TimestampMixin):
    """History of ticker/name changes, so historical joins survive renames
    and delisted issuers stay queryable (avoids survivorship bias, §3.1)."""

    __tablename__ = "company_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    previous_ticker: Mapped[str | None] = mapped_column(String(16), nullable=True)
    previous_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    effective_from: Mapped[dt.date] = mapped_column(nullable=False)
    effective_to: Mapped[dt.date | None] = mapped_column(nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    company = relationship("Company", back_populates="aliases")
