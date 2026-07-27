"""Transparent finance-domain calibration and event classification."""
from __future__ import annotations

import dataclasses
import re

from src.features.sentiment.model import SentimentModelResult

FINANCE_RULES_VERSION = "finance-rules-v1"

_POSITIVE_PATTERNS = (
    re.compile(r"\blaba(?: bersih)?\b.{0,35}\b(?:naik|tumbuh|melonjak|meningkat)\b", re.IGNORECASE),
    re.compile(r"\b(?:mencetak|membukukan) laba\b", re.IGNORECASE),
    re.compile(r"\bdividen\b.{0,30}\b(?:naik|meningkat|dibagikan|bayar)\b", re.IGNORECASE),
    re.compile(r"\b(?:upgrade|menaikkan) peringkat\b", re.IGNORECASE),
    re.compile(r"\bpendapatan\b.{0,35}\b(?:naik|tumbuh|melonjak|meningkat)\b", re.IGNORECASE),
)
_NEGATIVE_PATTERNS = (
    re.compile(r"\b(?:rugi bersih|membukukan rugi|gagal bayar|default|pailit|pkpu|fraud|korupsi)\b", re.IGNORECASE),
    re.compile(r"\b(?:laba|pendapatan)\b.{0,35}\b(?:turun|merosot|anjlok|menyusut)\b", re.IGNORECASE),
    re.compile(r"\b(?:downgrade|menurunkan) peringkat\b", re.IGNORECASE),
    re.compile(r"\b(?:suspensi|penghentian sementara) perdagangan\b", re.IGNORECASE),
)

_EVENT_RULES: tuple[tuple[str, str, str, re.Pattern], ...] = (
    ("default_or_insolvency", "critical", "structural", re.compile(r"\b(?:gagal bayar|default|pailit|pkpu)\b", re.IGNORECASE)),
    ("fraud_or_corruption", "critical", "structural", re.compile(r"\b(?:fraud|korupsi|penggelapan)\b", re.IGNORECASE)),
    ("trading_suspension", "high", "temporary", re.compile(r"\b(?:suspensi|penghentian sementara) perdagangan\b", re.IGNORECASE)),
    ("earnings_decline", "medium", "temporary", _NEGATIVE_PATTERNS[1]),
    ("earnings_growth", "medium", "temporary", _POSITIVE_PATTERNS[0]),
    ("dividend", "low", "temporary", re.compile(r"\bdividen\b", re.IGNORECASE)),
)


@dataclasses.dataclass(frozen=True, slots=True)
class FinancialEvent:
    category: str | None
    severity: str | None
    impact_horizon: str | None


def _signal(text: str) -> int:
    positive = sum(_has_unnegated_match(pattern, text) for pattern in _POSITIVE_PATTERNS)
    negative = sum(_has_unnegated_match(pattern, text) for pattern in _NEGATIVE_PATTERNS)
    return max(-2, min(2, positive - negative))


def _has_unnegated_match(pattern: re.Pattern, text: str) -> bool:
    for match in pattern.finditer(text):
        prefix = text[max(0, match.start() - 18) : match.start()]
        if not re.search(r"\b(?:tidak|bukan|tanpa)\s+(?:pernah\s+)?$", prefix, re.IGNORECASE):
            return True
    return False


def calibrate_financial_sentiment(text: str, result: SentimentModelResult) -> SentimentModelResult:
    """Nudge a general-domain model only when an explicit finance phrase exists."""
    signal = _signal(text)
    if signal == 0:
        return SentimentModelResult(
            model_id=f"{result.model_id}+{FINANCE_RULES_VERSION}",
            raw_label=result.raw_label,
            probabilities=dict(result.probabilities),
        )

    probabilities = dict(result.probabilities)
    positive = probabilities.get("Positive", 0.0)
    neutral = probabilities.get("Neutral", 0.0)
    negative = probabilities.get("Negative", 0.0)
    adjustment = min(0.70, 0.55 * abs(signal))
    if signal > 0:
        positive += adjustment
        neutral = max(0.0, neutral - adjustment * 0.7)
        negative = max(0.0, negative - adjustment * 0.3)
    else:
        negative += adjustment
        neutral = max(0.0, neutral - adjustment * 0.7)
        positive = max(0.0, positive - adjustment * 0.3)
    total = positive + neutral + negative
    calibrated = {
        "Positive": positive / total,
        "Neutral": neutral / total,
        "Negative": negative / total,
    }
    return SentimentModelResult(
        model_id=f"{result.model_id}+{FINANCE_RULES_VERSION}",
        raw_label=max(calibrated, key=calibrated.get),
        probabilities=calibrated,
    )


def classify_financial_event(text: str) -> FinancialEvent:
    for category, severity, horizon, pattern in _EVENT_RULES:
        if _has_unnegated_match(pattern, text):
            return FinancialEvent(category, severity, horizon)
    return FinancialEvent(None, None, None)
