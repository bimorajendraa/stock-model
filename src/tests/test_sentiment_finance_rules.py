"""Unit tests for transparent finance sentiment calibration."""
from __future__ import annotations

from src.features.sentiment.finance_rules import calibrate_financial_sentiment, classify_financial_event
from src.features.sentiment.model import SentimentModelResult


def _neutral_result() -> SentimentModelResult:
    return SentimentModelResult(
        model_id="general-test-model",
        raw_label="Neutral",
        probabilities={"Positive": 0.10, "Neutral": 0.80, "Negative": 0.10},
    )


def test_explicit_earnings_decline_corrects_neutral_bias():
    result = calibrate_financial_sentiment("Laba bersih emiten turun 45 persen", _neutral_result())
    assert result.raw_label == "Negative"
    assert result.probabilities["Negative"] > result.probabilities["Neutral"]
    assert result.model_id.endswith("+finance-rules-v1")


def test_explicit_earnings_growth_corrects_neutral_bias():
    result = calibrate_financial_sentiment("Laba bersih emiten tumbuh 45 persen", _neutral_result())
    assert result.raw_label == "Positive"
    assert result.probabilities["Positive"] > result.probabilities["Neutral"]


def test_no_finance_signal_preserves_probabilities():
    base = _neutral_result()
    result = calibrate_financial_sentiment("Direksi menghadiri acara tahunan", base)
    assert result.raw_label == "Neutral"
    assert result.probabilities == base.probabilities


def test_negated_default_phrase_is_not_negative_event():
    base = _neutral_result()
    result = calibrate_financial_sentiment("Perusahaan tidak gagal bayar obligasi", base)
    event = classify_financial_event("Perusahaan tidak gagal bayar obligasi")
    assert result.raw_label == "Neutral"
    assert event.category is None


def test_event_rules_record_severity_and_horizon():
    event = classify_financial_event("Perusahaan mengajukan PKPU setelah gagal bayar obligasi")
    assert event.category == "default_or_insolvency"
    assert event.severity == "critical"
    assert event.impact_horizon == "structural"
