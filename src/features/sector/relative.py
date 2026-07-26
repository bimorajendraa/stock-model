"""Sector-relative fundamental metrics -- pure functions, no DB (spec
section 3.5/8). Only meaningful now that real sector classification
exists (``docs/sector_classification.md``) -- comparing a company's ROE
to a "peer group" of real sector-mates it's genuinely a bank/miner/telco
alongside, not an arbitrary or fabricated grouping.

**Not the same as** `IndustryDataProvider.get_metrics` (spec section 3.5)
-- that interface is for metrics only obtainable from real sector-specific
disclosures (banking NPL/NIM/CAR, mining stripping ratio, etc.), which no
adapter in this project provides. This module instead computes a
cross-sectional **percentile rank** of a company's own already-computed
fundamental ratio (``financial_ratios``) against its real sector peers --
a legitimate, deterministic derived metric, not a disclosed one.
"""
from __future__ import annotations

MIN_PEERS = 3  # fewer peers than this makes a percentile look falsely precise -- not computable, never fabricated


def percentile_rank(value: float, peer_values: list[float]) -> float | None:
    """Where ``value`` (assumed to be one of ``peer_values``) ranks among
    its peers, 0-100. Ties share the midpoint rank rather than an
    arbitrary ordering. ``None`` when the peer group is too small."""
    if len(peer_values) < MIN_PEERS:
        return None
    below = sum(1 for v in peer_values if v < value)
    equal = sum(1 for v in peer_values if v == value)
    return (below + 0.5 * equal) / len(peer_values) * 100
