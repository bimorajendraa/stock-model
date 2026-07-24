"""Unit tests for reconciliation comparison logic (pure function, no DB)."""
from __future__ import annotations

from src.ingestion.reconciliation import compute_reconciliation


def test_matched_when_prices_identical():
    result = compute_reconciliation(6500.0, 6500.0)
    assert result.status == "matched"
    assert result.absolute_difference == 0


def test_within_tolerance_for_small_difference():
    result = compute_reconciliation(6500.0, 6510.0, tolerance_pct=0.5)  # ~0.15% diff
    assert result.status == "within_tolerance"


def test_mismatch_for_large_difference():
    result = compute_reconciliation(6500.0, 7000.0, tolerance_pct=0.5)
    assert result.status == "mismatch"


def test_verification_unavailable_when_no_second_source():
    result = compute_reconciliation(6500.0, None)
    assert result.status == "verification_unavailable"
    assert result.absolute_difference is None


def test_volume_difference_computed_when_both_present():
    result = compute_reconciliation(6500.0, 6500.0, primary_volume=1000, verification_volume=1200)
    assert result.volume_difference == 200


def test_volume_difference_none_when_one_missing():
    result = compute_reconciliation(6500.0, 6500.0, primary_volume=1000, verification_volume=None)
    assert result.volume_difference is None
