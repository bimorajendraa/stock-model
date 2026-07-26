"""Live test against the real pretrained model (downloads/loads real
weights, no DB needed) -- same "verify against the real thing, not a
mock" discipline as every other ``_live`` test file in this project.
Marked integration since it's slow (real model load) and network-
dependent on first run (weights get cached under
``~/.cache/huggingface`` after that).
"""
from __future__ import annotations

import pytest

from src.features.sentiment.model import derive_score_and_label, score_text

pytestmark = pytest.mark.integration


def test_clearly_positive_financial_sentence_scores_positive():
    result = score_text("Laba bersih perusahaan melonjak tajam, kinerja sangat positif tahun ini.")
    score, label = derive_score_and_label(result)
    assert result.raw_label == "Positive"
    assert score > 0
    assert label in ("positif", "sangat_positif")


def test_clearly_negative_financial_sentence_scores_negative():
    result = score_text("Perusahaan mencatat rugi besar dan sahamnya anjlok signifikan.")
    score, label = derive_score_and_label(result)
    assert result.raw_label == "Negative"
    assert score < 0
    assert label in ("negatif", "sangat_negatif")


def test_routine_announcement_scores_neutral():
    result = score_text("Rapat umum pemegang saham akan digelar pekan depan di Jakarta.")
    _, label = derive_score_and_label(result)
    assert result.raw_label == "Neutral"
    assert label == "netral"
