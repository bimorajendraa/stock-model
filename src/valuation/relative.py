"""Self-relative (own-history multiple) valuation -- pure functions, no
DB/network (spec section 8/10, section 2.15: valuation must be
deterministic code, never LLM-computed).

This module deliberately contains only the own-history method. Same-sector
peer valuation and explicit-assumption DCF live in `peer.py` and `dcf.py` and
are combined by `pipeline.py`.

**Known limitation, stated plainly**: this is "is this cheap or expensive
relative to its OWN past," not "intrinsic value" in the DCF sense --
and even that comparison is partly circular, since the historical P/E/P/B
series is itself built from past *market prices*, which already reflect
whatever sentiment/risk re-rating happened over that window, not a
price-independent fundamental anchor. The window is also short (this
project's fundamentals history is only ~4 years deep, see
`docs/fundamentals.md`), so the percentile range may simply reflect
whatever market regime occurred in those 4 years, not a stable long-run
range. This is disclosed in every result via `sensitivity`, not hidden.
"""
from __future__ import annotations

import numpy as np

MIN_HISTORY_POINTS = 3  # fewer points than this makes a percentile look
# falsely precise -- treated as not computable, never a fabricated number.


def percentile_fair_values(per_share_metric: float | None, multiple_history: list[float]) -> dict[str, float | None]:
    """``per_share_metric``: latest EPS (for the P/E method) or latest book
    value per share (for the P/B method). ``multiple_history``: that
    company's own historical P/E or P/B values (already point-in-time).
    Returns bear/base/bull fair-value estimates by applying the
    25th/50th/75th percentile of the company's own historical multiple to
    its current per-share metric -- ``None`` for every field when not
    computable (missing/non-positive metric, or too little history),
    never a fabricated 0."""
    if per_share_metric is None or per_share_metric <= 0 or len(multiple_history) < MIN_HISTORY_POINTS:
        return {"bear": None, "base": None, "bull": None, "p25_multiple": None, "p50_multiple": None, "p75_multiple": None, "n_points": len(multiple_history)}
    p25, p50, p75 = np.percentile(multiple_history, [25, 50, 75])
    return {
        "bear": float(per_share_metric * p25),
        "base": float(per_share_metric * p50),
        "bull": float(per_share_metric * p75),
        "p25_multiple": float(p25),
        "p50_multiple": float(p50),
        "p75_multiple": float(p75),
        "n_points": len(multiple_history),
    }


def combine_methods(estimates: dict[str, dict[str, float | None]]) -> dict:
    """``estimates``: {method_name: percentile_fair_values(...) result}.
    Equal-weight average across methods that produced a real (non-None)
    ``base`` estimate. ``conservative`` is the MINIMUM bear-case estimate
    among available methods, never an average -- "conservative" should
    mean the lower bound an investor could anchor on, not something
    smoothed toward the middle."""
    usable = {name: v for name, v in estimates.items() if v.get("base") is not None}
    if not usable:
        return {"bear": None, "base": None, "bull": None, "conservative": None, "methods_used": {}}

    weight = 1.0 / len(usable)

    def average_scenario(name: str) -> float | None:
        values = [float(value[name]) for value in usable.values() if value.get(name) is not None]
        return sum(values) / len(values) if values else None

    bear_values = [float(value["bear"]) for value in usable.values() if value.get("bear") is not None]
    return {
        "bear": average_scenario("bear"),
        "base": average_scenario("base"),
        "bull": average_scenario("bull"),
        "conservative": min(bear_values) if bear_values else None,
        "methods_used": {name: weight for name in usable},
    }
