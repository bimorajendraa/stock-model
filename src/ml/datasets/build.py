"""Assembles a model-ready dataset: technical_features (long, DB) ->
wide per company/date, joined with point-in-time labels, split into
train/validation/test with embargo+purging (spec sections 14-17).
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models.company import Company
from src.database.models.features import TechnicalFeature
from src.database.models.fundamentals import FinancialRatio
from src.database.models.market import MarketPriceClean
from src.ml.datasets.labeling import DEFAULT_HORIZONS, build_labels
from src.ml.datasets.splitting import DateSplitConfig, default_split_dates, purge_and_split


def _load_technical_features_wide(session: Session, company_ids: list[int]) -> pd.DataFrame:
    rows = session.execute(
        select(
            TechnicalFeature.company_id,
            TechnicalFeature.feature_date,
            TechnicalFeature.feature_name,
            TechnicalFeature.value,
        ).where(TechnicalFeature.company_id.in_(company_ids))
    ).all()
    if not rows:
        return pd.DataFrame()
    long_df = pd.DataFrame(rows, columns=["company_id", "feature_date", "feature_name", "value"])
    long_df["value"] = long_df["value"].astype(float)
    wide = long_df.pivot_table(index=["company_id", "feature_date"], columns="feature_name", values="value")
    return wide.reset_index()


def _load_close_prices(session: Session, company_ids: list[int]) -> pd.DataFrame:
    rows = session.execute(
        select(MarketPriceClean.company_id, MarketPriceClean.trade_date, MarketPriceClean.close).where(
            MarketPriceClean.company_id.in_(company_ids)
        )
    ).all()
    df = pd.DataFrame(rows, columns=["company_id", "trade_date", "close"])
    df["close"] = df["close"].astype(float)
    return df


def _load_fundamental_ratios_wide(session: Session, company_ids: list[int]) -> pd.DataFrame:
    """One row per (company_id, available_date) with a ``fund_<ratio>``
    column per base ratio name (the ``__annual``/``__quarterly`` suffix
    from ``financial_ratios.ratio_name`` is collapsed -- for a
    "most recently known value" feature, whichever statement type is more
    recently available should win, regardless of granularity). Only
    ``is_applicable`` rows are used -- a not-applicable ratio (e.g. a
    bank's current_ratio) must stay genuinely missing (NaN), never a
    fabricated 0, so the model can tell "unknown" from "zero"."""
    rows = session.execute(
        select(FinancialRatio.company_id, FinancialRatio.ratio_name, FinancialRatio.available_at, FinancialRatio.value)
        .where(FinancialRatio.company_id.in_(company_ids), FinancialRatio.is_applicable.is_(True))
    ).all()
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["company_id", "ratio_name", "available_at", "value"])
    df["value"] = df["value"].astype(float)
    # .astype("datetime64[ns]") pins the unit explicitly -- merge_asof
    # requires both merge-key columns to share the exact same datetime64
    # unit, and pd.to_datetime's inferred unit here (seconds, from
    # tz-aware source data) otherwise silently mismatches
    # _attach_fundamental_ratios's key (datetime64[us], from plain date
    # objects), raising a MergeError caught by a real integration test
    # rather than at runtime in production.
    df["available_date"] = pd.to_datetime(df["available_at"]).dt.tz_localize(None).dt.normalize().astype("datetime64[ns]")
    df["ratio_base"] = df["ratio_name"].str.rsplit("__", n=1).str[0]
    df = df.sort_values("available_date")

    wide = df.pivot_table(index=["company_id", "available_date"], columns="ratio_base", values="value", aggfunc="last")
    wide = wide.add_prefix("fund_").reset_index()
    return wide.sort_values("available_date")


def _attach_fundamental_ratios(df: pd.DataFrame, ratios_wide: pd.DataFrame) -> pd.DataFrame:
    """As-of join: each trading-day row gets the most recently *available*
    (per ``available_at``, never ``period_end``) value for every fund_*
    ratio column, per company -- a forward-fill that only uses information
    that was actually public by that date, never a future statement's
    number (spec section 3.3/17 point-in-time discipline)."""
    if ratios_wide.empty:
        return df
    df = df.sort_values("feature_date").reset_index(drop=True)
    df["_asof_date"] = pd.to_datetime(df["feature_date"]).astype("datetime64[ns]")
    merged = pd.merge_asof(
        df, ratios_wide, left_on="_asof_date", right_on="available_date", by="company_id", direction="backward"
    )
    return merged.drop(columns=["_asof_date", "available_date"])


def build_labeled_dataset(
    session: Session,
    tickers: list[str],
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    include_fundamentals: bool = False,
) -> pd.DataFrame:
    """One row per (company, date) with technical feature columns +
    fwd_return_*d / direction_*d label columns. Rows with all-NaN labels
    (end-of-history, no real outcome yet) are dropped -- can't train on a
    label that doesn't exist.

    ``include_fundamentals=True`` additionally attaches point-in-time
    ``fund_*`` ratio columns (see ``_attach_fundamental_ratios``) --
    default False keeps existing technical-only callers unchanged."""
    companies = {c.ticker: c for c in session.scalars(select(Company).where(Company.ticker.in_(tickers)))}
    company_ids = [c.id for c in companies.values()]
    id_to_ticker = {c.id: t for t, c in companies.items()}

    features_wide = _load_technical_features_wide(session, company_ids)
    prices = _load_close_prices(session, company_ids)

    label_frames = []
    for company_id, group in prices.groupby("company_id"):
        group = group.sort_values("trade_date")
        close = pd.Series(group["close"].to_numpy(), index=pd.DatetimeIndex(group["trade_date"]))
        labels = build_labels(close, horizons)
        labels["company_id"] = company_id
        labels["feature_date"] = labels.index.date
        # close itself is not one of the 36 technical_features rows (it
        # lives in market_prices_clean, not duplicated into that table) --
        # carried through here as a plain passthrough column, NOT meant to
        # be used as an ML input feature (raw price level isn't stationary/
        # scale-comparable across companies), only for baselines that
        # explicitly need it (e.g. the moving-average rule).
        labels["close"] = close.to_numpy()
        label_frames.append(labels.reset_index(drop=True))

    labels_df = pd.concat(label_frames, ignore_index=True) if label_frames else pd.DataFrame()

    if features_wide.empty or labels_df.empty:
        return pd.DataFrame()

    merged = features_wide.merge(labels_df, on=["company_id", "feature_date"], how="inner")
    label_cols = [c for c in merged.columns if c.startswith(("fwd_return_", "direction_"))]
    merged = merged.dropna(subset=label_cols, how="all")
    merged["ticker"] = merged["company_id"].map(id_to_ticker)

    if include_fundamentals:
        ratios_wide = _load_fundamental_ratios_wide(session, company_ids)
        merged = _attach_fundamental_ratios(merged, ratios_wide)

    return merged


def split_dataset(
    df: pd.DataFrame, horizon_days: int, embargo_days: int = 10
) -> tuple[dict[str, pd.DataFrame], DateSplitConfig]:
    """Computes the date split from the dataset's own date range and
    applies purge_and_split for the given horizon."""
    min_date: dt.date = df["feature_date"].min()
    max_date: dt.date = df["feature_date"].max()
    split = default_split_dates(min_date, max_date)
    split.embargo_days = embargo_days
    parts = purge_and_split(df, "feature_date", horizon_days, split)
    return parts, split
