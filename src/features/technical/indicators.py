"""Technical indicators (spec section 7). Pure functions over pandas
Series/DataFrames indexed by trade_date, ascending -- no I/O, no database,
independently testable against hand-computed reference values.

Deliberately implemented from scratch rather than via a third-party TA
library: spec section 2.15-16 requires all numeric computation be
deterministic code this project has validated itself, not a black box.
Every function's docstring states the exact convention used (e.g. Wilder's
smoothing vs. simple moving average) because these have historically been
a common source of subtle bugs/disagreement between charting platforms.

Market-relative features (beta, alpha, relative strength vs. IHSG) ARE
now implemented, but in ``market_relative.py``, not here -- they need the
IHSG index series (``docs/macro_data.md``, ``industry_series`` table)
alongside a company's own close series, a different input shape than
every other function in this module. Support/resistance (swing/fractal/
pivot ensemble) and turnover_ratio (needs shares_outstanding, not
available from any adapter -- see docs/data_sources.md) are still
deferred for the "needs data this project doesn't have yet" reason.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


# --- Trend -----------------------------------------------------------------

def sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window=window, min_periods=window).mean()


def ema(close: pd.Series, window: int) -> pd.Series:
    return close.ewm(span=window, adjust=False, min_periods=window).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """Returns columns: macd, signal, histogram."""
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    histogram = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "histogram": histogram})


def _wilder_smooth(series: pd.Series, window: int) -> pd.Series:
    """Wilder's smoothing (used by RSI/ATR/ADX in their original
    definitions) -- equivalent to an EWM with alpha=1/window. This is the
    convention most charting platforms (TradingView, etc.) use; a plain
    SMA-based RSI/ATR will disagree with those platforms' numbers."""
    return series.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    tr = _true_range(high, low, close)
    atr_smooth = _wilder_smooth(tr, window)
    plus_di = 100 * _wilder_smooth(plus_dm, window) / atr_smooth
    minus_di = 100 * _wilder_smooth(minus_dm, window) / atr_smooth

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return _wilder_smooth(dx, window)


# --- Momentum ----------------------------------------------------------------

def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = _wilder_smooth(gain, window)
    avg_loss = _wilder_smooth(loss, window)
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k_window: int = 14, d_window: int = 3) -> pd.DataFrame:
    """Returns columns: k, d."""
    lowest_low = low.rolling(window=k_window, min_periods=k_window).min()
    highest_high = high.rolling(window=k_window, min_periods=k_window).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low)
    d = k.rolling(window=d_window, min_periods=d_window).mean()
    return pd.DataFrame({"k": k, "d": d})


def rate_of_change(close: pd.Series, window: int) -> pd.Series:
    return (close / close.shift(window) - 1) * 100


def williams_r(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    highest_high = high.rolling(window=window, min_periods=window).max()
    lowest_low = low.rolling(window=window, min_periods=window).min()
    return -100 * (highest_high - close) / (highest_high - lowest_low)


def momentum_return(close: pd.Series, window: int) -> pd.Series:
    """Simple (not log) return over ``window`` trading days -- spec's
    momentum windows are 5/20/60/120/252 days."""
    return close / close.shift(window) - 1


# --- Volatility --------------------------------------------------------------

def bollinger_bands(close: pd.Series, window: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    """Returns columns: upper, middle, lower, bandwidth."""
    middle = sma(close, window)
    std = close.rolling(window=window, min_periods=window).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    bandwidth = (upper - lower) / middle
    return pd.DataFrame({"upper": upper, "middle": middle, "lower": lower, "bandwidth": bandwidth})


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    return pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    return _wilder_smooth(_true_range(high, low, close), window)


def historical_volatility(close: pd.Series, window: int) -> pd.Series:
    """Annualized rolling std of log returns."""
    log_returns = np.log(close / close.shift(1))
    return log_returns.rolling(window=window, min_periods=window).std() * np.sqrt(TRADING_DAYS_PER_YEAR)


def downside_volatility(close: pd.Series, window: int) -> pd.Series:
    """Annualized rolling std of *negative* log returns only (positive
    returns treated as 0 for this purpose) -- captures downside risk
    specifically, not symmetric volatility."""
    log_returns = np.log(close / close.shift(1))
    downside = log_returns.clip(upper=0)
    return (downside.pow(2).rolling(window=window, min_periods=window).mean().pow(0.5)) * np.sqrt(TRADING_DAYS_PER_YEAR)


# --- Volume and liquidity -----------------------------------------------------

def volume_sma(volume: pd.Series, window: int) -> pd.Series:
    return volume.rolling(window=window, min_periods=window).mean()


def volume_ratio(volume: pd.Series, window: int) -> pd.Series:
    return volume / volume_sma(volume, window)


def on_balance_volume(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


def accumulation_distribution(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    range_ = high - low
    money_flow_multiplier = ((close - low) - (high - close)) / range_.replace(0, np.nan)
    money_flow_multiplier = money_flow_multiplier.fillna(0)
    return (money_flow_multiplier * volume).cumsum()


def money_flow_index(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, window: int = 14) -> pd.Series:
    typical_price = (high + low + close) / 3
    raw_money_flow = typical_price * volume
    price_change = typical_price.diff()

    positive_flow = raw_money_flow.where(price_change > 0, 0.0)
    negative_flow = raw_money_flow.where(price_change < 0, 0.0)

    positive_sum = positive_flow.rolling(window=window, min_periods=window).sum()
    negative_sum = negative_flow.rolling(window=window, min_periods=window).sum()

    money_ratio = positive_sum / negative_sum
    return 100 - (100 / (1 + money_ratio))


def average_daily_traded_value(close: pd.Series, volume: pd.Series, window: int) -> pd.Series:
    return (close * volume).rolling(window=window, min_periods=window).mean()
