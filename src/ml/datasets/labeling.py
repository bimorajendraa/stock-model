"""Point-in-time labeling for multi-horizon return prediction (spec
sections 14-15).

Every label is a genuine forward return: label(t) uses close(t+h), which
is only ever valid for TRAINING (where the outcome already happened and
is in our historical data) -- these functions must never be called on
data being used as a model INPUT feature, only as the TARGET. Rows near
the end of a company's history don't have a real t+h outcome yet and are
labeled NaN, not guessed.

Deliberately narrower than spec section 14's full wishlist:
- "Beat IHSG" / sector-relative labels need an index/sector price series
  this project doesn't ingest yet (see docs/data_sources.md) -- omitted
  rather than faked against a proxy.
- Cross-sectional quantile rank IS implemented, but explicitly scoped to
  whatever universe of tickers is passed in (currently the top-50-by-
  market-cap set) -- it is never presented as a full-IDX percentile.
- 3-year/5-year scenario horizons are omitted for now: most of the
  current 50-company dataset doesn't have enough forward history past a
  ~1-year horizon for those long labels to have real outcomes yet either.
"""
from __future__ import annotations

import pandas as pd

DEFAULT_HORIZONS = (5, 20, 60, 120, 252)


def compute_forward_returns(close: pd.Series, horizons: tuple[int, ...] = DEFAULT_HORIZONS) -> pd.DataFrame:
    """Simple (not log) forward return per horizon: (close[t+h] / close[t]) - 1.
    NaN wherever t+h falls past the end of available history."""
    labels = {f"fwd_return_{h}d": close.shift(-h) / close - 1 for h in horizons}
    return pd.DataFrame(labels, index=close.index)


def compute_direction_labels(forward_returns: pd.DataFrame) -> pd.DataFrame:
    """Binary: 1 if forward return > 0, 0 if <= 0, NaN preserved."""
    return forward_returns.map(lambda r: r if pd.isna(r) else float(r > 0))


def compute_cross_sectional_quantile(
    forward_returns_by_ticker: dict[str, pd.Series], horizon_label: str
) -> dict[str, pd.Series]:
    """Ranks each ticker's forward return against the OTHER tickers in
    ``forward_returns_by_ticker`` on the same date -- a relative-
    performance label, scoped to this specific universe (spec's
    "quantile ranking" candidate, §15), not a full-market percentile.
    Returns a percentile in [0, 1] per ticker per date."""
    combined = pd.DataFrame({ticker: series for ticker, series in forward_returns_by_ticker.items()})
    ranks = combined.rank(axis=1, pct=True, na_option="keep")
    return {ticker: ranks[ticker].rename(f"{horizon_label}_quantile") for ticker in forward_returns_by_ticker}


def build_labels(close: pd.Series, horizons: tuple[int, ...] = DEFAULT_HORIZONS) -> pd.DataFrame:
    """Convenience: forward returns + direction labels for one ticker,
    long-format-ready (one column per horizon x label type)."""
    fwd = compute_forward_returns(close, horizons)
    direction = compute_direction_labels(fwd)
    direction.columns = [f"direction_{h}d" for h in horizons]
    return pd.concat([fwd, direction], axis=1)
