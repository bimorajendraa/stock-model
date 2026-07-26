"""Unit tests for the macro/industry series taxonomy -- no network, no DB."""
from __future__ import annotations

from src.data_sources.macro.taxonomy import SERIES_CATALOG


def test_every_series_routes_to_a_known_table():
    assert all(d.table in ("macro", "industry") for d in SERIES_CATALOG.values())


def test_every_series_has_a_name_and_unit():
    assert all(d.series_name and d.unit_of_measure for d in SERIES_CATALOG.values())
