"""Peer/sector-relative multiple valuation -- pure deterministic logic."""
from __future__ import annotations

import numpy as np

MIN_PEERS = 3


def peer_multiple_fair_values(
    per_share_metric: float | None,
    peer_multiples: list[float],
) -> dict[str, float | int | None]:
    usable = [value for value in peer_multiples if value > 0]
    if per_share_metric is None or per_share_metric <= 0 or len(usable) < MIN_PEERS:
        return {
            "bear": None,
            "base": None,
            "bull": None,
            "p25_multiple": None,
            "p50_multiple": None,
            "p75_multiple": None,
            "n_peers": len(usable),
        }
    p25, p50, p75 = np.percentile(usable, [25, 50, 75])
    return {
        "bear": float(per_share_metric * p25),
        "base": float(per_share_metric * p50),
        "bull": float(per_share_metric * p75),
        "p25_multiple": float(p25),
        "p50_multiple": float(p50),
        "p75_multiple": float(p75),
        "n_peers": len(usable),
    }
