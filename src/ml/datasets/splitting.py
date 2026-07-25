"""Date-based train/validation/test splitting with embargo and purging
(spec sections 16-17). Never a random split -- spec section 2.4 forbids
it for time-series data, and section 17 explicitly forbids random K-Fold.

Split boundaries are calendar dates, shared across every ticker -- not a
per-ticker row-count split. A row-count split would let one ticker's
"test" period be, in calendar time, earlier than another ticker's
"train" period when tickers have different history lengths (which they
do here: AADI has ~1.5 years, BBCA has ~10) -- exactly the kind of
cross-sectional leakage this avoids.
"""
from __future__ import annotations

import dataclasses
import datetime as dt

import pandas as pd


@dataclasses.dataclass
class DateSplitConfig:
    train_end: dt.date
    validation_start: dt.date
    validation_end: dt.date
    test_start: dt.date
    test_end: dt.date
    embargo_days: int = 10


def default_split_dates(min_date: dt.date, max_date: dt.date, train_frac: float = 0.65, val_frac: float = 0.15) -> DateSplitConfig:
    """~65/15/20 split of the actual available date range, calendar-day
    proportioned (not trading-day-precise, which is a fine approximation
    for choosing split boundaries)."""
    total_days = (max_date - min_date).days
    train_end = min_date + dt.timedelta(days=int(total_days * train_frac))
    validation_end = min_date + dt.timedelta(days=int(total_days * (train_frac + val_frac)))
    return DateSplitConfig(
        train_end=train_end,
        validation_start=train_end + dt.timedelta(days=1),
        validation_end=validation_end,
        test_start=validation_end + dt.timedelta(days=1),
        test_end=max_date,
    )


def purge_and_split(df: pd.DataFrame, date_col: str, horizon_days: int, split: DateSplitConfig) -> dict[str, pd.DataFrame]:
    """Splits ``df`` (must have a date column, one row per
    company/date) into train/validation/test, purging any row from
    train/validation whose label window (date -> date + horizon_days)
    would cross into the next split's embargo zone."""
    dates = pd.to_datetime(df[date_col])
    label_end = dates + pd.to_timedelta(horizon_days, unit="D")
    embargo = pd.Timedelta(days=split.embargo_days)

    train_mask = (dates.dt.date <= split.train_end) & (
        label_end <= pd.Timestamp(split.validation_start) - embargo
    )
    validation_mask = (
        (dates.dt.date >= split.validation_start)
        & (dates.dt.date <= split.validation_end)
        & (label_end <= pd.Timestamp(split.test_start) - embargo)
    )
    test_mask = (dates.dt.date >= split.test_start) & (dates.dt.date <= split.test_end)

    return {
        "train": df[train_mask.to_numpy()],
        "validation": df[validation_mask.to_numpy()],
        "test": df[test_mask.to_numpy()],
    }
