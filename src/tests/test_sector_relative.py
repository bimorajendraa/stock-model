"""Unit tests for pure sector-relative percentile-rank logic -- no DB, no network."""
from __future__ import annotations

import pytest

from src.features.sector.relative import MIN_PEERS, percentile_rank


def test_percentile_rank_hand_computed():
    # 5 peers: 10, 20, 30, 40, 50 -- ranking 30 (the median)
    peers = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile_rank(30.0, peers) == pytest.approx(50.0)


def test_percentile_rank_lowest_value():
    peers = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile_rank(10.0, peers) == pytest.approx(10.0)  # 0 below + 0.5*1 equal, /5 = 0.1 -> 10%


def test_percentile_rank_highest_value():
    peers = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile_rank(50.0, peers) == pytest.approx(90.0)  # 4 below + 0.5*1 equal, /5 = 0.9 -> 90%


def test_percentile_rank_ties_share_midpoint():
    peers = [10.0, 20.0, 20.0, 20.0, 30.0]
    # ranking one of the three 20.0s: 1 below, 3 equal (including itself) -> (1 + 0.5*3)/5 = 0.5 -> 50%
    assert percentile_rank(20.0, peers) == pytest.approx(50.0)


def test_percentile_rank_too_few_peers_is_not_applicable():
    assert len([10.0, 20.0]) < MIN_PEERS
    assert percentile_rank(10.0, [10.0, 20.0]) is None


def test_percentile_rank_exactly_min_peers_is_computable():
    peers = [10.0, 20.0, 30.0]
    assert len(peers) == MIN_PEERS
    assert percentile_rank(20.0, peers) is not None
