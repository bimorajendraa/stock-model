"""Pretrained Indonesian sentiment classifier -- a real deep-learning model
(fine-tuned BERT), never an LLM (spec section 2.15/2.12: sentiment is a
numeric model output that must be reproducible and auditable, not narrated
or guessed by an LLM).

Model choice, checked live before use (2026-07-26), same "verify, don't
assume" discipline as every other data source in this project:

- A finance-domain-specific alternative was tried first --
  ``michaelmanurung/finbert-indonesia`` (BERT fine-tuned on 500 manually
  labeled Indonesian financial headlines). Its own model card reports
  **accuracy 0.299, F1 0.276** on its eval set -- worse than the 0.333
  random baseline for 3 balanced classes. Domain match alone doesn't make
  a model usable; rejected on real reported numbers, not a hunch.
- ``ayameRushia/bert-base-indonesian-1.5G-sentiment-analysis-smsa`` is used
  instead: BERT (``cahya/bert-base-indonesian-1.5G``) fine-tuned on
  IndoNLU's SmSA benchmark (general-domain Indonesian product/app reviews,
  **not finance-specific** -- a real, disclosed limitation, not hidden).
  Reports 93.73% accuracy on that benchmark, the best real number found
  among the candidates checked. Labels: ``Positive`` / ``Neutral`` /
  ``Negative``.
"""
from __future__ import annotations

import dataclasses
from functools import lru_cache

MODEL_ID = "ayameRushia/bert-base-indonesian-1.5G-sentiment-analysis-smsa"

# Not from the model itself (it only ever emits Positive/Neutral/Negative) --
# our own disclosed heuristic for splitting each polarity into a "sangat_"
# (very) variant vs. the plain one, to fill the 5-point
# news_sentiment.sentiment_label scale (spec section 3.6).
_SANGAT_THRESHOLD = 0.75


@dataclasses.dataclass(frozen=True)
class SentimentModelResult:
    model_id: str
    raw_label: str  # the model's own argmax: "Positive" | "Neutral" | "Negative"
    probabilities: dict[str, float]  # e.g. {"Positive": 0.81, "Neutral": 0.12, "Negative": 0.07}


@lru_cache(maxsize=1)
def _get_pipeline():
    from transformers import pipeline  # heavy import (torch) -- deferred until actually scoring something

    return pipeline("text-classification", model=MODEL_ID, top_k=None)


def score_text(text: str) -> SentimentModelResult:
    """Real inference against the pretrained model -- the default scorer
    used by ``features.sentiment.pipeline``. Tests inject a fake scorer
    instead of calling this, to avoid loading ~500MB of model weights per
    test run.
    """
    clf = _get_pipeline()
    predictions = clf(text, truncation=True)[0]
    probabilities = {item["label"]: float(item["score"]) for item in predictions}
    raw_label = max(probabilities, key=probabilities.get)
    return SentimentModelResult(model_id=MODEL_ID, raw_label=raw_label, probabilities=probabilities)


def derive_score_and_label(result: SentimentModelResult) -> tuple[float, str]:
    """Continuous score in [-1, 1] (P(positive) - P(negative)) plus the
    5-point Indonesian label the DB schema expects. The 5-point split is
    this project's own heuristic layered on the model's native 3 classes
    (see ``_SANGAT_THRESHOLD`` above), not something the model reports.
    """
    positive = result.probabilities.get("Positive", 0.0)
    negative = result.probabilities.get("Negative", 0.0)
    score = positive - negative

    if result.raw_label == "Positive":
        label = "sangat_positif" if positive >= _SANGAT_THRESHOLD else "positif"
    elif result.raw_label == "Negative":
        label = "sangat_negatif" if negative >= _SANGAT_THRESHOLD else "negatif"
    else:
        label = "netral"
    return score, label
