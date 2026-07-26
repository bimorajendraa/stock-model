"""Live test against the real bi.go.id SEKI catalog and interest-rate
XLS download -- real network, real legacy-Excel parsing. Excluded from CI
(``--ignore-glob='**/*_live.py'``)."""
from __future__ import annotations

import datetime as dt

import pytest

from src.data_sources.base import ValidationStatus
from src.data_sources.macro.bi_seki import BankIndonesiaSEKIInterestRateAdapter, SEKIDatasetDiscoveryAdapter

pytestmark = pytest.mark.integration


def test_discover_finds_real_seki_catalog():
    adapter = SEKIDatasetDiscoveryAdapter()
    entries = adapter.discover()
    assert len(entries) > 50  # real catalog has ~108 real tables
    assert all(e.xls_url.startswith("https://www.bi.go.id/SEKI/tabel/") for e in entries)
    sections = {e.section for e in entries}
    assert "I. UANG DAN BANK" in sections


def test_interest_rate_adapter_returns_real_plausible_rates():
    adapter = BankIndonesiaSEKIInterestRateAdapter()
    lending = adapter.get_series("bi_lending_facility_rate", dt.date(2020, 1, 1), dt.date(2026, 12, 31))
    deposit = adapter.get_series("bi_deposit_facility_rate", dt.date(2020, 1, 1), dt.date(2026, 12, 31))

    assert lending.validation_status == ValidationStatus.VALID
    assert deposit.validation_status == ValidationStatus.VALID
    assert len(lending.value) > 20
    assert len(deposit.value) > 20

    # Real corridor check: Lending Facility is always the ceiling, Deposit
    # Facility the floor, around the same-period BI-Rate -- verify the
    # ordering holds for every date both series report, not just that
    # numbers exist.
    deposit_by_date = {p.observation_date: p.value for p in deposit.value}
    for point in lending.value:
        if point.observation_date in deposit_by_date:
            assert point.value > deposit_by_date[point.observation_date]
