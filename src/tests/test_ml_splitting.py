"""Unit tests for date-based splitting with embargo/purging."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from src.ml.datasets.splitting import DateSplitConfig, default_split_dates, purge_and_split


def test_default_split_dates_proportions():
    split = default_split_dates(dt.date(2016, 1, 1), dt.date(2026, 1, 1), train_frac=0.65, val_frac=0.15)
    assert split.train_end < split.validation_start
    assert split.validation_end < split.test_start
    assert split.test_end == dt.date(2026, 1, 1)
    total_days = (dt.date(2026, 1, 1) - dt.date(2016, 1, 1)).days
    train_days = (split.train_end - dt.date(2016, 1, 1)).days
    assert train_days == pytest.approx(total_days * 0.65, abs=2)


def test_purge_and_split_basic_membership():
    split = DateSplitConfig(
        train_end=dt.date(2026, 1, 10),
        validation_start=dt.date(2026, 1, 11),
        validation_end=dt.date(2026, 1, 20),
        test_start=dt.date(2026, 1, 21),
        test_end=dt.date(2026, 1, 31),
        embargo_days=2,
    )
    dates = pd.date_range("2026-01-01", "2026-01-31", freq="D")
    df = pd.DataFrame({"trade_date": dates, "value": range(len(dates))})

    result = purge_and_split(df, "trade_date", horizon_days=5, split=split)

    assert result["train"]["trade_date"].max().date() <= split.train_end
    assert result["validation"]["trade_date"].min().date() >= split.validation_start
    assert result["test"]["trade_date"].min().date() >= split.test_start
    assert result["test"]["trade_date"].max().date() <= split.test_end


def test_purge_and_split_removes_rows_near_boundary():
    # horizon=5, embargo=2: a train row at train_end (Jan 10) has label_end
    # Jan 15, which is well past validation_start(Jan11)-embargo(2d)=Jan9 --
    # must be purged even though its own date is within train_end.
    split = DateSplitConfig(
        train_end=dt.date(2026, 1, 10),
        validation_start=dt.date(2026, 1, 11),
        validation_end=dt.date(2026, 1, 20),
        test_start=dt.date(2026, 1, 21),
        test_end=dt.date(2026, 1, 31),
        embargo_days=2,
    )
    dates = pd.date_range("2026-01-01", "2026-01-31", freq="D")
    df = pd.DataFrame({"trade_date": dates, "value": range(len(dates))})

    result = purge_and_split(df, "trade_date", horizon_days=5, split=split)
    train_dates = set(result["train"]["trade_date"].dt.date)

    assert dt.date(2026, 1, 10) not in train_dates  # purged: label window crosses embargo zone
    assert dt.date(2026, 1, 3) in train_dates  # label_end Jan 8 <= Jan 9 (validation_start - embargo) -- kept


def test_purge_and_split_no_overlap_between_splits():
    split = DateSplitConfig(
        train_end=dt.date(2026, 1, 10),
        validation_start=dt.date(2026, 1, 11),
        validation_end=dt.date(2026, 1, 20),
        test_start=dt.date(2026, 1, 21),
        test_end=dt.date(2026, 1, 31),
        embargo_days=2,
    )
    dates = pd.date_range("2026-01-01", "2026-01-31", freq="D")
    df = pd.DataFrame({"trade_date": dates, "value": range(len(dates))})

    result = purge_and_split(df, "trade_date", horizon_days=5, split=split)
    train_idx = set(result["train"].index)
    val_idx = set(result["validation"].index)
    test_idx = set(result["test"].index)

    assert train_idx.isdisjoint(val_idx)
    assert val_idx.isdisjoint(test_idx)
    assert train_idx.isdisjoint(test_idx)
