"""Market-relative technical features vs. IHSG (spec section 7) -- pure
functions over pandas Series, no I/O. Needs both a company's own close
series AND the IHSG index level series (``docs/macro_data.md``), a
different input shape than every function in ``indicators.py``, hence a
separate module.

**Known, honestly-stated limitation**: ``rolling_alpha`` here is NOT
CAPM alpha. Real CAPM alpha needs a risk-free rate, and this project has
no verified Indonesia-domestic risk-free-rate source (same gap already
documented in ``docs/valuation.md``/``docs/macro_data.md`` blocking DCF).
This is a simplified "excess return not explained by beta" proxy:
``alpha = stock_return - beta * market_return``, with no risk-free rate
subtracted. Never call this a true CAPM alpha anywhere downstream, and
never substitute the global `us_10y_treasury_yield` series for a real
Indonesian risk-free rate here either (`docs/macro_data.md`'s own
limitation note).
"""
from __future__ import annotations

import pandas as pd


def daily_returns(close: pd.Series) -> pd.Series:
    return close.pct_change()


def rolling_beta(stock_returns: pd.Series, market_returns: pd.Series, window: int) -> pd.Series:
    """Cov(stock, market) / Var(market) over a rolling window -- the
    standard definition, computed from daily returns, never from raw
    price levels (which would conflate trend with co-movement)."""
    covariance = stock_returns.rolling(window=window, min_periods=window).cov(market_returns)
    market_variance = market_returns.rolling(window=window, min_periods=window).var()
    return covariance / market_variance


def rolling_alpha(stock_returns: pd.Series, market_returns: pd.Series, beta: pd.Series) -> pd.Series:
    """Simplified excess-return proxy, NOT CAPM alpha -- see module
    docstring. ``beta`` must already be aligned to the same index (i.e.
    the output of ``rolling_beta`` for the same window)."""
    return stock_returns - beta * market_returns


def relative_strength(stock_momentum: pd.Series, market_momentum: pd.Series) -> pd.Series:
    """Difference in cumulative return over the same window (both from
    ``indicators.momentum_return``) -- positive means the stock
    outperformed IHSG over that window, not a prediction of future
    outperformance."""
    return stock_momentum - market_momentum
