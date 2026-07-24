"""Price adjustment policy (spec section 7).

Three distinct values, never conflated:
- ``raw_price`` -- exactly what the provider returned, never touched.
- ``provider_adjusted_price`` -- the provider's own adjusted close (e.g.
  yfinance's "Adj Close"). Known limitation: yfinance's Adj Close adjusts
  for splits AND dividends together -- there is no separately-available
  split-only-adjusted value from the providers implemented so far, so
  ``provider_split_adjusted`` and ``provider_all_adjusted`` policies
  currently resolve to the same underlying number. Documented here rather
  than silently pretended to be precise.
- ``internally_adjusted_price`` -- computed *only* from corporate actions
  with ``verification_status == "officially_verified"`` (spec: "hanya
  dihitung dari corporate actions yang lolos validasi"). As of this
  writing nothing in ``corporate_actions`` has been officially verified
  (no IDX-official confirmation workflow exists yet), so this policy
  currently has no verified inputs to compute from in practice -- the
  algorithm is real and tested, but has nothing to chew on yet.
"""
from __future__ import annotations

import datetime as dt

VALID_POLICIES = frozenset(
    {"raw", "provider_split_adjusted", "provider_all_adjusted", "internally_verified_adjusted"}
)


def resolve_price(
    raw_close: float | None,
    provider_adjusted_close: float | None,
    internally_adjusted_close: float | None,
    policy: str,
) -> tuple[float | None, str]:
    """Returns (price_to_use, source_used). Always falls back to raw if the
    policy's preferred value is unavailable -- never returns None when a
    raw price exists."""
    if policy not in VALID_POLICIES:
        raise ValueError(f"unknown price adjustment policy: {policy!r} (valid: {sorted(VALID_POLICIES)})")

    if policy == "raw":
        return raw_close, "raw"

    if policy in ("provider_split_adjusted", "provider_all_adjusted"):
        if provider_adjusted_close is not None:
            return provider_adjusted_close, "provider"
        return raw_close, "raw_fallback"

    if internally_adjusted_close is not None:
        return internally_adjusted_close, "internal"
    return raw_close, "raw_fallback"


def compute_internally_adjusted_close(
    raw_by_date: dict[dt.date, float],
    verified_splits: list[tuple[dt.date, float, float]],
) -> dict[dt.date, float]:
    """Back-adjust historical closes for splits, so pre-split and
    post-split prices are directly comparable for technical analysis.

    ``verified_splits`` must already be filtered to
    ``verification_status == "officially_verified"`` by the caller -- this
    function does not know about verification status, it just computes.

    Each entry is (ex_date, split_from, split_to) -- e.g. a 1-for-5 split
    (1 share becomes 5) is (ex_date, 1, 5): every price *before* ex_date is
    divided by (split_to/split_from) so it's comparable to post-split
    prices. Multiple splits compound correctly since each pass operates on
    the already-adjusted values from the previous pass.
    """
    adjusted = dict(raw_by_date)
    for ex_date, split_from, split_to in sorted(verified_splits, key=lambda s: s[0]):
        ratio = split_to / split_from
        if ratio <= 0:
            continue
        for d, price in adjusted.items():
            if d < ex_date:
                adjusted[d] = price / ratio
    return adjusted
