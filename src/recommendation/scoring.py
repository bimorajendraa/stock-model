"""Deterministic recommendation scoring -- pure functions, no DB/network
(spec section 21, section 2.15: recommendations must be deterministic
code, never LLM-decided).

**Deliberately excludes any ML-predicted signal.** Tahap 4's baseline
models were tested three independent ways (more features, longer
horizons, a different market-cap tier -- `docs/model_methodology.md`) and
none showed a validated edge; several actively overfit. Feeding an
unproven, near-random signal into a recommendation would manufacture
false confidence, the opposite of spec section 18's "never claim a model
is free of overfitting -- report the evidence" -- the honest response to
"the model doesn't work yet" is to leave it out, not down-weight it a
little and call it done. This engine is built entirely from `valuation_
results` (self-relative multiple valuation, `docs/valuation.md`) and
`financial_ratios` (`docs/fundamentals.md`) -- today's-state facts, not
predictions.

Every threshold below (10% ROE, 1.0x D/E, etc.) is a simple, transparent,
commonly-cited equity-analysis rule of thumb -- not a statistically
validated cutoff, not fabricated data. Documented plainly so it can be
revisited, not presented as more rigorous than it is.
"""
from __future__ import annotations

VALUATION_UNDERVALUED = "undervalued"
VALUATION_FAIR = "fair"
VALUATION_OVERVALUED = "overvalued"

QUALITY_HEALTHY = "healthy"
QUALITY_MIXED = "mixed"
QUALITY_WEAK = "weak"

LABEL_LAYAK_DIBELI = "LAYAK_DIBELI"
LABEL_AKUMULASI_BERTAHAP = "AKUMULASI_BERTAHAP"
LABEL_TUNGGU_HARGA = "TUNGGU_HARGA"
LABEL_HOLD = "HOLD"
LABEL_HINDARI = "HINDARI"
LABEL_DATA_TIDAK_MENCUKUPI = "DATA_TIDAK_MENCUKUPI"

ROE_HEALTHY_THRESHOLD = 0.10  # 10% -- common equity-analysis rule of thumb, not a statistically fit cutoff
DEBT_TO_EQUITY_HIGH_THRESHOLD = 1.0


def classify_valuation_position(
    current_price: float | None, fair_value_bear: float | None, fair_value_bull: float | None
) -> str | None:
    """None when the valuation inputs are missing -- caller must treat
    that as "not computable," never default to "fair."""
    if current_price is None or fair_value_bear is None or fair_value_bull is None:
        return None
    if current_price < fair_value_bear:
        return VALUATION_UNDERVALUED
    if current_price > fair_value_bull:
        return VALUATION_OVERVALUED
    return VALUATION_FAIR


def classify_fundamental_quality(
    net_margin: float | None, roe: float | None, debt_to_equity: float | None
) -> str | None:
    """``debt_to_equity`` may legitimately be ``None`` (not_applicable --
    e.g. a bank, where this project's ratio taxonomy doesn't define a
    comparable leverage figure) without blocking the classification;
    ``net_margin``/``roe`` missing DOES block it -- profitability is the
    minimum bar to classify quality at all."""
    if net_margin is None or roe is None:
        return None
    if net_margin <= 0 or roe <= 0:
        return QUALITY_WEAK
    if roe >= ROE_HEALTHY_THRESHOLD and (debt_to_equity is None or debt_to_equity < DEBT_TO_EQUITY_HIGH_THRESHOLD):
        return QUALITY_HEALTHY
    return QUALITY_MIXED


def combine_recommendation(valuation_position: str | None, fundamental_quality: str | None) -> str:
    """Weak fundamentals -> HINDARI regardless of valuation (a cheap
    stock with weak fundamentals is a value trap, not a bargain).
    Otherwise driven by valuation position. Either input missing ->
    DATA_TIDAK_MENCUKUPI, never a guessed label."""
    if valuation_position is None or fundamental_quality is None:
        return LABEL_DATA_TIDAK_MENCUKUPI
    if fundamental_quality == QUALITY_WEAK:
        return LABEL_HINDARI
    if valuation_position == VALUATION_UNDERVALUED:
        return LABEL_LAYAK_DIBELI if fundamental_quality == QUALITY_HEALTHY else LABEL_AKUMULASI_BERTAHAP
    if valuation_position == VALUATION_OVERVALUED:
        return LABEL_TUNGGU_HARGA
    return LABEL_HOLD


def compute_confidence(valuation_data_quality: float | None, n_fundamental_inputs: int, n_fundamental_inputs_target: int = 3) -> float:
    """Simple 0-1 completeness heuristic (how much of the valuation and
    fundamental input data was actually available), NOT a statistical
    confidence interval -- same honesty convention as
    ``ValuationResult.data_quality_score`` (see docs/valuation.md)."""
    if valuation_data_quality is None:
        return 0.0
    fundamental_completeness = min(1.0, n_fundamental_inputs / n_fundamental_inputs_target)
    return round((float(valuation_data_quality) + fundamental_completeness) / 2, 4)
