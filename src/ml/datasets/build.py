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


def build_labeled_dataset(
    session: Session, tickers: list[str], horizons: tuple[int, ...] = DEFAULT_HORIZONS
) -> pd.DataFrame:
    """One row per (company, date) with technical feature columns +
    fwd_return_*d / direction_*d label columns. Rows with all-NaN labels
    (end-of-history, no real outcome yet) are dropped -- can't train on a
    label that doesn't exist."""
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
