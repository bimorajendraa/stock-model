"""Unit tests for price adjustment policy resolution and split back-adjustment."""
from __future__ import annotations

import datetime as dt

import pytest

from src.common.price_adjustment import compute_internally_adjusted_close, resolve_price


def test_raw_policy_ignores_adjusted_values():
    price, source = resolve_price(100.0, 90.0, 80.0, "raw")
    assert price == 100.0
    assert source == "raw"


def test_provider_split_adjusted_uses_provider_value():
    price, source = resolve_price(100.0, 90.0, None, "provider_split_adjusted")
    assert price == 90.0
    assert source == "provider"


def test_provider_policy_falls_back_to_raw_when_missing():
    price, source = resolve_price(100.0, None, None, "provider_split_adjusted")
    assert price == 100.0
    assert source == "raw_fallback"


def test_internally_verified_uses_internal_value():
    price, source = resolve_price(100.0, 90.0, 85.0, "internally_verified_adjusted")
    assert price == 85.0
    assert source == "internal"


def test_internally_verified_falls_back_to_raw_when_no_verified_data():
    price, source = resolve_price(100.0, 90.0, None, "internally_verified_adjusted")
    assert price == 100.0
    assert source == "raw_fallback"


def test_unknown_policy_raises():
    with pytest.raises(ValueError):
        resolve_price(100.0, None, None, "not_a_real_policy")


def test_compute_internally_adjusted_close_single_split():
    raw = {
        dt.date(2021, 10, 10): 30000.0,  # before 1:5 split
        dt.date(2021, 10, 14): 6000.0,  # after split
    }
    splits = [(dt.date(2021, 10, 13), 1, 5)]
    adjusted = compute_internally_adjusted_close(raw, splits)
    assert adjusted[dt.date(2021, 10, 10)] == pytest.approx(6000.0)  # 30000 / 5
    assert adjusted[dt.date(2021, 10, 14)] == 6000.0  # unaffected, already post-split


def test_compute_internally_adjusted_close_compounds_multiple_splits():
    raw = {dt.date(2020, 1, 1): 100.0}
    splits = [
        (dt.date(2020, 6, 1), 1, 2),  # 1:2 split
        (dt.date(2021, 6, 1), 1, 5),  # then 1:5 split
    ]
    adjusted = compute_internally_adjusted_close(raw, splits)
    assert adjusted[dt.date(2020, 1, 1)] == pytest.approx(100.0 / 2 / 5)


def test_compute_internally_adjusted_close_no_verified_splits_is_noop():
    raw = {dt.date(2020, 1, 1): 100.0}
    adjusted = compute_internally_adjusted_close(raw, [])
    assert adjusted == raw
