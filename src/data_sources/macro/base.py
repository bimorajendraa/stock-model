"""Macroeconomic + commodity/index series provider interface (spec §3.4)."""
from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod

from src.data_sources.base import SourcedValue


class SeriesPoint:
    __slots__ = ("observation_date", "value")

    def __init__(self, observation_date: dt.date, value: float | None) -> None:
        self.observation_date = observation_date
        self.value = value


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
