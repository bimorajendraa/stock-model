"""Unit tests for pure logic in the Yahoo fundamentals adapter -- no
network, no database. Live-network behavior is covered separately by
``test_fundamentals_yahoo_adapter_live`` (marked ``integration``)."""
from __future__ import annotations

import datetime as dt

from src.data_sources.fundamentals.taxonomy import ACCOUNT_CODE_SECTIONS
from src.data_sources.fundamentals.yahoo_finance import (
    _ANNUAL_LAG_DAYS,
    _QUARTERLY_LAG_DAYS,
    _YAHOO_FIELD_NAMES,
    _estimated_available_at,
    _fiscal_period,
)


def test_every_yahoo_field_has_a_taxonomy_section():
    # Would already fail at import time via the module-level assert, but
    # spelled out here so a future taxonomy/field-map drift shows up as a
    # named, discoverable test failure rather than only an import crash.
    assert set(_YAHOO_FIELD_NAMES) == set(ACCOUNT_CODE_SECTIONS)


def test_fiscal_period_annual():
    assert _fiscal_period(dt.date(2025, 12, 31), "annual") == "2025FY"


def test_fiscal_period_quarterly_maps_month_to_quarter():
    assert _fiscal_period(dt.date(2025, 3, 31), "quarterly") == "2025Q1"
    assert _fiscal_period(dt.date(2025, 6, 30), "quarterly") == "2025Q2"
    assert _fiscal_period(dt.date(2025, 9, 30), "quarterly") == "2025Q3"
    assert _fiscal_period(dt.date(2025, 12, 31), "quarterly") == "2025Q4"


def test_estimated_available_at_is_strictly_after_period_end():
    # The whole point of the estimate: available_at must never be
    # earlier than (or equal to) period_end -- that would be exactly the
    # point-in-time leakage this project forbids.
    period_end = dt.date(2025, 12, 31)
    annual = _estimated_available_at(period_end, "annual")
    quarterly = _estimated_available_at(period_end, "quarterly")
    assert annual.date() == period_end + dt.timedelta(days=_ANNUAL_LAG_DAYS)
    assert quarterly.date() == period_end + dt.timedelta(days=_QUARTERLY_LAG_DAYS)
    assert annual.date() > period_end
    assert quarterly.date() > period_end


def test_annual_lag_is_longer_than_or_equal_to_quarterly_lag():
    # Conservative-estimate invariant: annual reports have a longer real
    # filing deadline (audited) than interim reports, so the safe
    # (over-)estimate should reflect that, not just use one flat number.
    assert _ANNUAL_LAG_DAYS >= _QUARTERLY_LAG_DAYS
