"""Pure unit tests for the score->label derivation heuristic
(``derive_score_and_label``) -- no model load, no DB. Hand-built
``SentimentModelResult`` instances stand in for real model output."""
from __future__ import annotations

from src.features.sentiment.model import SentimentModelResult, derive_score_and_label


def _result(raw_label: str, positive: float, neutral: float, negative: float) -> SentimentModelResult:
    return SentimentModelResult(
        model_id="test-model",
        raw_label=raw_label,
        probabilities={"Positive": positive, "Neutral": neutral, "Negative": negative},
    )


def test_strong_positive_gets_sangat_positif():
    score, label = derive_score_and_label(_result("Positive", 0.90, 0.06, 0.04))
    assert label == "sangat_positif"
    assert score == 0.90 - 0.04


def test_mild_positive_gets_positif_not_sangat():
    score, label = derive_score_and_label(_result("Positive", 0.60, 0.30, 0.10))
    assert label == "positif"
    assert score == 0.60 - 0.10


def test_strong_negative_gets_sangat_negatif():
    score, label = derive_score_and_label(_result("Negative", 0.03, 0.07, 0.90))
    assert label == "sangat_negatif"
    assert score == 0.03 - 0.90


def test_mild_negative_gets_negatif_not_sangat():
    _, label = derive_score_and_label(_result("Negative", 0.10, 0.30, 0.60))
    assert label == "negatif"


def test_neutral_argmax_has_no_sangat_variant_regardless_of_confidence():
    score, label = derive_score_and_label(_result("Neutral", 0.05, 0.93, 0.02))
    assert label == "netral"
    assert score == 0.05 - 0.02


def test_threshold_boundary_is_inclusive():
    # exactly at _SANGAT_THRESHOLD (0.75) should count as "sangat"
    _, label = derive_score_and_label(_result("Positive", 0.75, 0.20, 0.05))
    assert label == "sangat_positif"
