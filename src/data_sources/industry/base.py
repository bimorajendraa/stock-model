"""Sector-specific metric provider interface (spec §3.5).

Distinct from ``macro`` (economy-wide series) and ``fundamentals``
(statement line items): this covers metrics only obtainable from
sector-specific disclosures or registries -- e.g. banking NPL/NIM/CAR from
OJK-style reporting, mining production/reserves from company operational
reports. Which metric names are expected per sector is config, not code
(see src/database/models/sector.py docstring).
"""
from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod

from src.data_sources.base import SourcedValue


class IndustryDataProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def sector_code(self) -> str:
        """Which sector_registry.sector_code this adapter serves."""

    @abstractmethod
    def get_metrics(
        self, ticker: str, fiscal_period: str
    ) -> SourcedValue[dict[str, float | str | None]]:
        """metric_name -> value for one company x period. Metrics the
        company did not disclose must be absent from the dict, never
        fabricated as 0 or null-filled (spec §3.5: "Jangan mengarang
        metrik apabila perusahaan tidak mempublikasikannya")."""

    @abstractmethod
    def get_series(
        self, series_code: str, start: dt.date, end: dt.date
    ) -> SourcedValue[list[tuple[dt.date, float | None]]]:
        """Commodity/industry-wide series relevant to this sector."""
