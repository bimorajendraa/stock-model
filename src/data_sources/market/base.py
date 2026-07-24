"""Market data (OHLCV, corporate actions) provider interface (spec §3.2).

At least two independent adapters must implement this (spec §3.2: "minimal
dua adapter data pasar agar tersedia mekanisme fallback dan cross-check").
Implementations live in sibling modules (Tahap 2) and must never be called
directly by business logic -- always through this interface, so a provider
can be swapped without touching ingestion/feature/model code (spec §2.8).
"""
from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod

from src.data_sources.base import SourcedValue


class OHLCVBar:
    """Plain data holder for one trading day; wrapped in SourcedValue by
    the adapter so provenance travels with the whole bar, not per-field."""

    __slots__ = (
        "close",
        "high",
        "low",
        "open",
        "trade_date",
        "transaction_frequency",
        "transaction_value",
        "volume",
    )

    def __init__(
        self,
        trade_date: dt.date,
        open: float | None,
        high: float | None,
        low: float | None,
        close: float | None,
        volume: int | None,
        transaction_value: float | None = None,
        transaction_frequency: int | None = None,
    ) -> None:
        self.trade_date = trade_date
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.transaction_value = transaction_value
        self.transaction_frequency = transaction_frequency


class MarketDataProvider(ABC):
    """Contract every OHLCV / corporate-action adapter must satisfy."""

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    def list_active_tickers(self) -> SourcedValue[list[str]]:
        """All currently-listed IDX tickers this provider knows about."""

    @abstractmethod
    def get_ohlcv(
        self, ticker: str, start: dt.date, end: dt.date
    ) -> SourcedValue[list[OHLCVBar]]:
        """Raw (unadjusted) daily bars for [start, end]. Adjustment happens
        downstream in preprocessing, never inside the adapter (spec §3.2:
        "Pisahkan harga mentah dan harga yang sudah disesuaikan")."""

    @abstractmethod
    def get_corporate_actions(
        self, ticker: str, start: dt.date, end: dt.date
    ) -> SourcedValue[list[dict]]:
        """Splits, reverse splits, rights issues, bonus shares, ticker/name
        changes announced in [start, end]."""
