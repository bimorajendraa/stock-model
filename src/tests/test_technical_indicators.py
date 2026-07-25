"""Unit tests for technical indicators -- pure functions, no I/O.

Where a full external reference table isn't practical to transcribe, tests
verify against hand-computable small series or well-known mathematical
properties (bounded ranges, monotonic-input behavior, etc.) instead.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features.technical import indicators as ind


def _series(values):
    return pd.Series(values, index=pd.date_range("2026-01-01", periods=len(values), freq="D"))


# --- SMA / EMA ---------------------------------------------------------------

def test_sma_hand_computed():
    s = _series([1, 2, 3, 4, 5])
    result = ind.sma(s, 3)
    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[1])
    assert result.iloc[2] == pytest.approx(2.0)  # (1+2+3)/3
    assert result.iloc[3] == pytest.approx(3.0)  # (2+3+4)/3
    assert result.iloc[4] == pytest.approx(4.0)  # (3+4+5)/3


def test_sma_constant_series_equals_constant():
    s = _series([10.0] * 10)
    result = ind.sma(s, 5)
    assert result.dropna().eq(10.0).all()


def test_ema_reacts_faster_than_sma_to_a_jump():
    s = _series([10.0] * 20 + [20.0] * 5)
    sma_result = ind.sma(s, 10)
    ema_result = ind.ema(s, 10)
    # After the jump, EMA should have moved further toward the new value than SMA
    assert ema_result.iloc[-1] > sma_result.iloc[-1]


# --- MACD ----------------------------------------------------------------

def test_macd_histogram_equals_macd_minus_signal():
    s = _series(np.linspace(100, 150, 60))
    result = ind.macd(s)
    valid = result.dropna()
    pd.testing.assert_series_equal(
        valid["histogram"], valid["macd"] - valid["signal"], check_names=False
    )


def test_macd_positive_for_sustained_uptrend():
    s = _series(np.linspace(100, 200, 60))
    result = ind.macd(s)
    assert result["macd"].iloc[-1] > 0  # fast EMA above slow EMA in an uptrend


# --- RSI -------------------------------------------------------------------

def test_rsi_bounded_0_100():
    rng = np.random.default_rng(42)
    s = _series(100 + np.cumsum(rng.normal(0, 1, 100)))
    result = ind.rsi(s, 14).dropna()
    assert (result >= 0).all()
    assert (result <= 100).all()


def test_rsi_approaches_100_for_monotonic_increase():
    s = _series(np.arange(1, 50, dtype=float))  # strictly increasing, no losses at all
    result = ind.rsi(s, 14).dropna()
    assert (result > 99).all()  # all gains, no losses -> RSI near 100


def test_rsi_approaches_0_for_monotonic_decrease():
    s = _series(np.arange(50, 1, -1, dtype=float))
    result = ind.rsi(s, 14).dropna()
    assert (result < 1).all()


# --- ADX ---------------------------------------------------------------------

def test_adx_non_negative():
    rng = np.random.default_rng(1)
    close = 100 + np.cumsum(rng.normal(0, 1, 100))
    high = close + rng.uniform(0.5, 1.5, 100)
    low = close - rng.uniform(0.5, 1.5, 100)
    result = ind.adx(_series(high), _series(low), _series(close), 14).dropna()
    assert (result >= 0).all()


# --- Stochastic / Williams %R ------------------------------------------------

def test_stochastic_bounded_0_100():
    rng = np.random.default_rng(2)
    close = 100 + np.cumsum(rng.normal(0, 1, 60))
    high = close + 1
    low = close - 1
    result = ind.stochastic(_series(high), _series(low), _series(close)).dropna()
    assert (result["k"] >= 0).all() and (result["k"] <= 100).all()
    assert (result["d"] >= 0).all() and (result["d"] <= 100).all()


def test_stochastic_k_is_100_at_period_high():
    close = _series([10, 11, 12, 13, 20])  # last close is the highest of the window
    high = close
    low = close - 1
    result = ind.stochastic(high, low, close, k_window=5, d_window=1)
    assert result["k"].iloc[-1] == pytest.approx(100.0)


def test_williams_r_bounded_negative_100_to_0():
    rng = np.random.default_rng(3)
    close = 100 + np.cumsum(rng.normal(0, 1, 60))
    high = close + 1
    low = close - 1
    result = ind.williams_r(_series(high), _series(low), _series(close)).dropna()
    assert (result >= -100).all() and (result <= 0).all()


# --- Rate of change / momentum -----------------------------------------------

def test_rate_of_change_hand_computed():
    s = _series([100, 105, 110, 121])
    result = ind.rate_of_change(s, 1)
    assert result.iloc[1] == pytest.approx(5.0)  # (105/100 - 1) * 100
    assert result.iloc[3] == pytest.approx(10.0)  # (121/110 - 1) * 100


def test_momentum_return_hand_computed():
    s = _series([100, 110, 121, 133.1])
    result = ind.momentum_return(s, 2)
    assert result.iloc[2] == pytest.approx(0.21)  # 121/100 - 1
    assert result.iloc[3] == pytest.approx(0.21)  # 133.1/110 - 1


# --- Bollinger Bands / ATR ----------------------------------------------------

def test_bollinger_bands_ordering():
    rng = np.random.default_rng(4)
    s = _series(100 + np.cumsum(rng.normal(0, 1, 60)))
    result = ind.bollinger_bands(s).dropna()
    assert (result["upper"] >= result["middle"]).all()
    assert (result["middle"] >= result["lower"]).all()


def test_bollinger_bands_zero_std_collapses_to_middle():
    s = _series([10.0] * 30)
    result = ind.bollinger_bands(s).dropna()
    assert (result["upper"] == result["middle"]).all()
    assert (result["lower"] == result["middle"]).all()


def test_atr_non_negative():
    rng = np.random.default_rng(5)
    close = 100 + np.cumsum(rng.normal(0, 1, 60))
    high = close + rng.uniform(0.1, 2, 60)
    low = close - rng.uniform(0.1, 2, 60)
    result = ind.atr(_series(high), _series(low), _series(close)).dropna()
    assert (result >= 0).all()


def test_historical_volatility_zero_for_constant_price():
    s = _series([100.0] * 30)
    result = ind.historical_volatility(s, 10).dropna()
    assert (result == 0).all()


def test_downside_volatility_zero_for_monotonic_increase():
    s = _series(np.arange(1, 50, dtype=float))  # never goes down
    result = ind.downside_volatility(s, 10).dropna()
    assert (result == 0).all()


# --- Volume --------------------------------------------------------------

def test_volume_ratio_one_when_volume_equals_average():
    s = _series([1000.0] * 20)
    result = ind.volume_ratio(s, 10).dropna()
    assert np.allclose(result.to_numpy(), 1.0)


def test_obv_increases_on_up_day_decreases_on_down_day():
    close = _series([10, 11, 10, 12])
    volume = _series([100, 200, 300, 400])
    result = ind.on_balance_volume(close, volume)
    assert result.iloc[0] == 0  # no prior day to compare
    assert result.iloc[1] == 200  # up day: +volume
    assert result.iloc[2] == 200 - 300  # down day: -volume
    assert result.iloc[3] == 200 - 300 + 400  # up day: +volume


def test_accumulation_distribution_handles_zero_range_without_error():
    high = _series([10, 10, 11])
    low = _series([10, 10, 9])  # first bar has high == low (zero range)
    close = _series([10, 10, 10])
    volume = _series([100, 100, 100])
    result = ind.accumulation_distribution(high, low, close, volume)
    assert not result.isna().any()  # zero-range bar must not produce NaN/inf


def test_money_flow_index_bounded_0_100():
    rng = np.random.default_rng(6)
    close = 100 + np.cumsum(rng.normal(0, 1, 60))
    high = close + 1
    low = close - 1
    volume = pd.Series(rng.uniform(1000, 5000, 60), index=_series(close).index)
    result = ind.money_flow_index(_series(high), _series(low), _series(close), volume).dropna()
    assert (result >= 0).all() and (result <= 100).all()


def test_average_daily_traded_value_hand_computed():
    close = _series([10, 20])
    volume = _series([100, 200])
    result = ind.average_daily_traded_value(close, volume, 2)
    assert result.iloc[1] == pytest.approx((10 * 100 + 20 * 200) / 2)
