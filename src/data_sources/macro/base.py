"""Macroeconomic + commodity/index series provider interface (spec §3.4)."""
from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod

from src.data_sources.base import SourcedValue


class SeriesPoint:
    """``available_at``: when this specific observation actually became
    public, if the provider can determine it per-point (e.g. BPS: end of
    the observed month + a real publication-lag estimate). ``None`` means
    the caller should fall back to the batch-level ``SourcedValue.
    available_at`` -- but that fallback is only point-in-time-correct for
    same-day data (e.g. today's market close); for a multi-year backfill
    it would wrongly claim a 2016 observation only became available
    "now". Adapters fetching historical series should set this
    explicitly rather than rely on the fallback."""

    __slots__ = ("available_at", "observation_date", "value")

    def __init__(self, observation_date: dt.date, value: float | None, available_at: dt.datetime | None = None) -> None:
        self.observation_date = observation_date
        self.value = value
        self.available_at = available_at


class MacroDataProvider(ABC):
    """One adapter typically covers one publisher (e.g. Bank Indonesia, BPS,
    a global macro API) -- ``series_code`` values it supports are documented
    by the concrete implementation, not fixed here."""

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    def supported_series(self) -> list[str]: ...

    @abstractmethod
    def get_series(
        self, series_code: str, start: dt.date, end: dt.date
    ) -> SourcedValue[list[SeriesPoint]]: ...
