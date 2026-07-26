"""Unit tests for pure sector-classification key derivation -- no DB, no network."""
from __future__ import annotations

from src.ingestion.sector_classification import _SECTOR_CODE_MAX_LEN, _sector_code, _slug


def test_slug_basic():
    assert _slug("Financial Services") == "financial_services"
    assert _slug("Banks - Regional") == "banks_regional"


def test_sector_code_never_exceeds_db_column_length():
    # Real bug this project hit live: sector_code is VARCHAR(32); a naive
    # slug of "Financial Services" + "Insurance - Property & Casualty"
    # is 49 chars and overflowed the column.
    long_sector = "A Very Long Sector Name That Keeps Going"
    long_industry = "An Even Longer Industry Sub-Classification Name"
    code = _sector_code(long_sector, long_industry)
    assert len(code) <= _SECTOR_CODE_MAX_LEN


def test_sector_code_distinguishes_industries_within_same_sector():
    # Real bug this project hit live: two different industries under the
    # same broad sector must not produce the same code (sector_code has
    # a global UNIQUE constraint).
    code_a = _sector_code("Financial Services", "Banks - Regional")
    code_b = _sector_code("Financial Services", "Insurance - Property & Casualty")
    assert code_a != code_b


def test_sector_code_is_deterministic():
    assert _sector_code("Technology", "Software - Infrastructure") == _sector_code(
        "Technology", "Software - Infrastructure"
    )


def test_sector_code_handles_missing_industry():
    code = _sector_code("Energy", None)
    assert len(code) <= _SECTOR_CODE_MAX_LEN
    assert code  # non-empty
