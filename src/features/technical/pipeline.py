"""market_prices_clean -> technical_features (spec section 7).

Indicators are computed on **adjustment-scaled OHLC**, not raw: every
price column is multiplied by the same per-row ``adjustment_factor``
already stored in ``market_prices_clean`` (adjusted_close/close), so a
stock split doesn't show up as a fake one-day crash in a moving average or
RSI. Volume is left unscaled. This is the standard charting-platform
convention (scale the whole OHLC bar by one factor, not just close).

Output is long-format (company_id, feature_date, feature_name, value,
feature_set_version) -- see src/database/models/features.py's docstring
for why: one row per company/date/table would need a migration for every
new indicator, and spec section 7 enumerates far more than fit reasonably
as columns.
"""
from __future__ import annotations

import dataclasses
import math

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.database.models.company import Company
from src.database.models.features import TechnicalFeature
from src.database.models.macro import IndustrySeries
from src.database.models.market import MarketPriceClean
from src.features.technical import indicators as ind
from src.features.technical import market_relative as mrel

FEATURE_SET_VERSION = "v2"  # v2 adds market-relative features (beta/alpha/relative_strength vs IHSG)

MOMENTUM_WINDOWS = (5, 20, 60, 120, 252)
SMA_WINDOWS = (5, 10, 20, 50, 100, 200)
BETA_ALPHA_WINDOWS = (60, 252)  # ~1 quarter and ~1 year, standard beta-estimation conventions


@dataclasses.dataclass
class TechnicalFeatureOutcome:
    ticker: str
    dates_processed: int = 0
    rows_written: int = 0
    skipped_reason: str | None = None


def _load_clean_prices(session: Session, company_id: int) -> pd.DataFrame:
    rows = session.scalars(
        select(MarketPriceClean).where(MarketPriceClean.company_id == company_id).order_by(MarketPriceClean.trade_date)
    ).all()
    if not rows:
        return pd.DataFrame()

    index = pd.DatetimeIndex([r.trade_date for r in rows])
    df = pd.DataFrame(
        {
            "open": [float(r.open) if r.open is not None else None for r in rows],
            "high": [float(r.high) if r.high is not None else None for r in rows],
            "low": [float(r.low) if r.low is not None else None for r in rows],
            "close": [float(r.close) if r.close is not None else None for r in rows],
            "volume": [float(r.volume) if r.volume is not None else None for r in rows],
            "adjustment_factor": [float(r.adjustment_factor) if r.adjustment_factor is not None else 1.0 for r in rows],
        },
        index=index,
    )
    for col in ("open", "high", "low", "close"):
        df[col] = df[col] * df["adjustment_factor"]
    return df


def _load_ihsg_series(session: Session) -> pd.Series:
    """IHSG (IDX Composite) daily close level, date-indexed -- from
    ``industry_series`` (``docs/macro_data.md``). Not company-specific,
    loaded once per call and reused; empty if the macro sync hasn't been
    run yet, in which case market-relative features are simply not
    computed (never fabricated) rather than erroring."""
    rows = session.execute(
        select(IndustrySeries.observation_date, IndustrySeries.value)
        .where(IndustrySeries.series_code == "ihsg_composite")
        .order_by(IndustrySeries.observation_date)
    ).all()
    if not rows:
        return pd.Series(dtype=float)
    index = pd.DatetimeIndex([r.observation_date for r in rows])
    return pd.Series([float(r.value) for r in rows], index=index)


def _compute_market_relative(df: pd.DataFrame, ihsg: pd.Series) -> dict[str, pd.Series]:
    if ihsg.empty:
        return {}

    # Inner-align to dates both series actually have -- a stock's
    # trading-halt gaps or IHSG's own missing dates must never be
    # silently filled; unmatched dates just don't get a market-relative
    # value for that row (same "insufficient" convention as every other
    # indicator here).
    market_close = ihsg.reindex(df.index)
    if market_close.notna().sum() < min(BETA_ALPHA_WINDOWS):
        return {}  # not enough overlapping history for even the shortest window -- longer windows
        # naturally come back NaN via rolling's own min_periods and get dropped downstream,
        # same as sma_200 on a company with <200 days of price history.

    stock_returns = mrel.daily_returns(df["close"])
    market_returns = mrel.daily_returns(market_close)

    features: dict[str, pd.Series] = {}
    for window in BETA_ALPHA_WINDOWS:
        beta = mrel.rolling_beta(stock_returns, market_returns, window)
        features[f"beta_{window}"] = beta
        features[f"alpha_{window}"] = mrel.rolling_alpha(stock_returns, market_returns, beta)

    for window in MOMENTUM_WINDOWS:
        stock_momentum = ind.momentum_return(df["close"], window)
        market_momentum = ind.momentum_return(market_close, window)
        features[f"relative_strength_{window}"] = mrel.relative_strength(stock_momentum, market_momentum)

    return features


def _compute_all(df: pd.DataFrame) -> dict[str, pd.Series]:
    close, high, low, volume = df["close"], df["high"], df["low"], df["volume"]
    features: dict[str, pd.Series] = {}

    for window in SMA_WINDOWS:
        features[f"sma_{window}"] = ind.sma(close, window)
    features["ema_12"] = ind.ema(close, 12)
    features["ema_26"] = ind.ema(close, 26)

    macd_df = ind.macd(close)
    features["macd"] = macd_df["macd"]
    features["macd_signal"] = macd_df["signal"]
    features["macd_histogram"] = macd_df["histogram"]

    features["adx_14"] = ind.adx(high, low, close, 14)
    features["rsi_14"] = ind.rsi(close, 14)

    stoch_df = ind.stochastic(high, low, close, 14, 3)
    features["stoch_k_14"] = stoch_df["k"]
    features["stoch_d_3"] = stoch_df["d"]

    features["roc_10"] = ind.rate_of_change(close, 10)
    features["williams_r_14"] = ind.williams_r(high, low, close, 14)

    for window in MOMENTUM_WINDOWS:
        features[f"momentum_{window}"] = ind.momentum_return(close, window)

    bb_df = ind.bollinger_bands(close, 20, 2.0)
    features["bb_upper_20"] = bb_df["upper"]
    features["bb_middle_20"] = bb_df["middle"]
    features["bb_lower_20"] = bb_df["lower"]
    features["bb_bandwidth_20"] = bb_df["bandwidth"]

    features["atr_14"] = ind.atr(high, low, close, 14)
    features["hist_vol_20"] = ind.historical_volatility(close, 20)
    features["hist_vol_60"] = ind.historical_volatility(close, 60)
    features["downside_vol_20"] = ind.downside_volatility(close, 20)

    features["volume_sma_20"] = ind.volume_sma(volume, 20)
    features["volume_ratio_20"] = ind.volume_ratio(volume, 20)
    features["obv"] = ind.on_balance_volume(close, volume)
    features["ad_line"] = ind.accumulation_distribution(high, low, close, volume)
    features["mfi_14"] = ind.money_flow_index(high, low, close, volume, 14)
    features["adtv_20"] = ind.average_daily_traded_value(close, volume, 20)

    return features


def compute_technical_features(session: Session, ticker: str) -> TechnicalFeatureOutcome:
    outcome = TechnicalFeatureOutcome(ticker=ticker)

    company = session.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        outcome.skipped_reason = "no matching Company row"
        return outcome

    df = _load_clean_prices(session, company.id)
    if df.empty:
        outcome.skipped_reason = "no clean price data -- run market build-clean first"
        return outcome

    outcome.dates_processed = len(df)
    feature_series = _compute_all(df)
    feature_series.update(_compute_market_relative(df, _load_ihsg_series(session)))

    rows = []
    for feature_name, series in feature_series.items():
        for trade_date, value in series.items():
            # Postgres NUMERIC cannot store inf/-inf/nan (unlike float8) --
            # a handful of ratio-based indicators (e.g. volume_ratio when
            # volume_sma is 0) can produce those on real edge cases, so
            # this filters on finiteness, not just NaN via dropna().
            if not math.isfinite(value):
                continue
            rows.append(
                {
                    "company_id": company.id,
                    "feature_date": trade_date.date(),
                    "feature_name": feature_name,
                    "value": float(value),
                    "feature_set_version": FEATURE_SET_VERSION,
                }
            )

    if not rows:
        return outcome

    # No natural unique constraint on (company_id, feature_date,
    # feature_name) exists on this long-format table (Tahap 1 design
    # didn't anticipate needing upsert-by-name) -- clear this company's
    # rows first so recomputation is idempotent rather than duplicating.
    clear_technical_features(session, company.id)

    chunk_size = 5000
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        session.execute(insert(TechnicalFeature).values(chunk))

    outcome.rows_written = len(rows)
    return outcome


def clear_technical_features(session: Session, company_id: int) -> None:
    """Delete existing rows for a company before recomputation, so re-running
    compute_technical_features is idempotent (no natural unique constraint
    exists on technical_features to use ON CONFLICT with -- see Tahap 1's
    long-format design, which didn't anticipate needing upsert-by-name)."""
    session.query(TechnicalFeature).filter(TechnicalFeature.company_id == company_id).delete()
