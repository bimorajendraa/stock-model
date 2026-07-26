"""Unit tests for market-relative technical features -- pure functions, no I/O."""
from __future__ import annotations

import pandas as pd
import pytest

from src.features.technical import market_relative as mrel


def _series(values):
    return pd.Series(values, index=pd.date_range("2026-01-01", periods=len(values), freq="D"))


def test_daily_returns_hand_computed():
    close = _series([100.0, 110.0, 99.0])
    result = mrel.daily_returns(close)
    assert pd.isna(result.iloc[0])
    assert result.iloc[1] == pytest.approx(0.10)
    assert result.iloc[2] == pytest.approx(-0.10)


def test_rolling_beta_exact_proportional_relationship():
    # Stock returns are exactly 1.5x market returns every day -- beta
    # over a window covering all of them must be exactly 1.5.
    market_returns = _series([0.01, 0.02, -0.01, 0.03, 0.01, -0.02, 0.02, 0.01, -0.01, 0.02])
    stock_returns = market_returns * 1.5
    beta = mrel.rolling_beta(stock_returns, market_returns, window=10)
    assert beta.iloc[-1] == pytest.approx(1.5, rel=1e-6)


def test_rolling_beta_insufficient_history_is_nan():
    market_returns = _series([0.01, 0.02, -0.01])
    stock_returns = market_returns * 1.2
    beta = mrel.rolling_beta(stock_returns, market_returns, window=10)
    assert beta.isna().all()  # never a falsely-precise beta from too little history


def test_rolling_alpha_zero_when_relationship_is_exactly_beta_scaled():
    # stock = beta * market exactly, every day -- alpha (excess return
    # not explained by beta) must be exactly 0.
    market_returns = _series([0.01, 0.02, -0.01, 0.03, 0.01, -0.02, 0.02, 0.01, -0.01, 0.02])
    stock_returns = market_returns * 1.5
    beta = mrel.rolling_beta(stock_returns, market_returns, window=10)
    alpha = mrel.rolling_alpha(stock_returns, market_returns, beta)
    assert alpha.iloc[-1] == pytest.approx(0.0, abs=1e-9)


def test_rolling_alpha_captures_constant_excess_return():
    # stock = market + constant daily excess -- adding a constant to
    # every day doesn't change covariance with the market (cov(market+c,
    # market) = var(market)), so beta must stay exactly 1.0, and alpha
    # (stock - beta*market) must then equal exactly the constant excess.
    market_returns = _series([0.01, 0.02, -0.01, 0.03, 0.01, -0.02, 0.02, 0.01, -0.01, 0.02])
    excess = 0.005
    stock_returns = market_returns + excess
    beta = mrel.rolling_beta(stock_returns, market_returns, window=10)
    alpha = mrel.rolling_alpha(stock_returns, market_returns, beta)
    assert beta.iloc[-1] == pytest.approx(1.0, abs=1e-9)
    assert alpha.iloc[-1] == pytest.approx(excess, abs=1e-9)


def test_relative_strength_hand_computed():
    stock_momentum = _series([0.20, 0.15, -0.05])
    market_momentum = _series([0.10, 0.15, 0.05])
    result = mrel.relative_strength(stock_momentum, market_momentum)
    assert result.iloc[0] == pytest.approx(0.10)  # outperformed
    assert result.iloc[1] == pytest.approx(0.0)  # matched
    assert result.iloc[2] == pytest.approx(-0.10)  # underperformed
