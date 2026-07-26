# Recommendation engine (Tahap 5, spec section 21)

Status: one deterministic engine implemented and verified against real
data (`src/recommendation/scoring.py`, `src/recommendation/pipeline.py`),
writing into the `recommendation_results` table from the Tahap 1 schema.

## The most important design decision: no ML signal is used

Tahap 4's baseline models were tested three independent ways -- adding
fundamental features, longer label horizons, a different market-cap tier
(`docs/model_methodology.md`) -- and none showed a validated edge; some
actively overfit. This engine **does not use any ML prediction at all**.
Feeding an unproven, near-random signal into a recommendation would
manufacture false confidence -- the opposite of spec section 18's "never
claim a model is free of overfitting, report the evidence." The honest
response to "the model doesn't work yet" is to leave it out, not
down-weight it a little and call the job done. This is recorded
explicitly in every result (`scores.ml_signal_used = False`), not a
silent omission someone could mistake for an oversight.

The engine is built entirely from two things that ARE real, computed,
and defensible:

1. **Valuation position** (`valuation_results`, `docs/valuation.md`) --
   is the current price below/within/above the company's own
   bear-to-bull fair-value range.
2. **Fundamental quality** (`financial_ratios`, `docs/fundamentals.md`)
   -- latest net margin, ROE, and debt-to-equity.

Both are today's-state facts computed deterministically from real data,
not predictions of the future.

## Scoring logic

`src/recommendation/scoring.py`:

- **Valuation position**: `undervalued` (price < bear fair value),
  `overvalued` (price > bull fair value), or `fair` (in between). `None`
  (not computable) if any input is missing -- never defaults to "fair."
- **Fundamental quality**: `weak` if net margin or ROE is <= 0;
  `healthy` if ROE >= 10% AND (debt-to-equity is not_applicable, e.g. a
  bank, OR debt-to-equity < 1.0x); `mixed` otherwise. `None` if net
  margin or ROE is missing (debt-to-equity alone missing does NOT block
  classification -- not_applicable is not the same as missing-and-fatal).
  **Every threshold here (10% ROE, 1.0x D/E) is a simple, commonly-cited
  equity-analysis rule of thumb, not a statistically validated cutoff** --
  documented plainly so it can be revisited, not presented as more
  rigorous than it is.
- **Combination**: weak fundamentals -> `HINDARI` regardless of
  valuation (a cheap stock with weak fundamentals is a value trap, not a
  bargain). Otherwise driven by valuation position: undervalued ->
  `LAYAK_DIBELI` (healthy) or `AKUMULASI_BERTAHAP` (mixed); overvalued ->
  `TUNGGU_HARGA`; fair -> `HOLD`. Either input missing ->
  `DATA_TIDAK_MENCUKUPI`, never a guessed label.
- **Confidence**: a simple 0-1 completeness heuristic (average of the
  valuation's own `data_quality_score` and how many of the 3 fundamental
  inputs were available) -- not a statistical confidence interval, same
  honesty convention as `ValuationResult.data_quality_score`.

## What's recorded per result

- `scores` (JSONB): every component value that went into the decision --
  valuation position, fundamental quality, current price, bear/base/bull
  fair values, net margin, ROE, debt-to-equity, and the explicit
  `ml_signal_used: false` marker.
- `guardrails_triggered`: e.g. `high_leverage` (debt-to-equity > 2.0x),
  `valuation_not_computable`, `fundamental_quality_not_computable`.
- `entry_zone`: for `LAYAK_DIBELI`/`AKUMULASI_BERTAHAP`, the
  conservative-to-base fair value range; for `TUNGGU_HARGA`, the
  conservative-to-bear range (the price zone worth waiting for).
- `suggested_horizon`: a fixed `"6-12 bulan"` string -- the implicit
  mean-reversion assumption behind the self-relative valuation method,
  **not** derived from data, stated as an assumption.
- `investment_style`: left `NULL` -- not classified in this first cut,
  rather than fabricating a "value"/"growth" label without a real basis.

## Real run results (2026-07-25)

`python -m src.cli recommendation compute --tickers <top-50-by-market-cap>`:

- **50/50 companies succeeded**, 0 skipped, **0 `DATA_TIDAK_MENCUKUPI`**
  -- fundamentals coverage for this set is solid enough that every
  company had both a valuation and a classifiable fundamental profile.
- Label distribution: **25 HOLD, 13 TUNGGU_HARGA, 7 AKUMULASI_BERTAHAP,
  4 HINDARI, 1 LAYAK_DIBELI** -- a real, varied distribution (not
  uniform/fabricated-looking).
- Confidence ranged 0.625-0.969 (median 0.969) -- most companies have
  full data; a few (e.g. CDIA, a recent IPO) score lower from shorter
  fundamentals history, consistent with `docs/fundamentals.md`'s finding
  that recent IPOs have less real history, not a bug.
- **7 companies triggered `high_leverage`** -- a real, useful guardrail
  flag independent of the label itself.
- Spot-checked for consistency with `docs/valuation.md`'s own numbers:
  TLKM/ASII (priced well above their own historical fair-value range) ->
  `TUNGGU_HARGA`; GOTO (priced below its own historical range) ->
  `AKUMULASI_BERTAHAP`; UNVR is the sole `LAYAK_DIBELI` -- a real,
  plausible story (Unilever Indonesia's share price has been under
  sustained pressure while core profitability metrics stayed healthy),
  not an arbitrary pick.

## Idempotency

Same day-scoped pattern as `valuation_results`
(`docs/valuation.md`'s idempotency section): re-running today replaces
today's row only, past snapshots stay untouched. Verified by
`test_compute_recommendation_is_idempotent_per_day_not_across_days`.

## CLI

```
python -m src.cli recommendation compute --tickers BBCA,TLKM,ASII
python -m src.cli recommendation compute --offset 0 --limit 150
```

## What's not built yet

- **investment_style classification** -- left `NULL`, no real
  methodology decided yet.
- **Guardrails beyond `high_leverage`** -- spec section 21 likely expects
  a richer guardrail set (e.g. going-concern flags, data staleness) --
  this project's `going_concern_flag`/`auditor_opinion` are always
  `None`/`False` since Yahoo Finance doesn't expose them
  (`docs/fundamentals.md`), so those specific guardrails aren't
  computable from current data either.
- **Incorporating a validated ML signal** -- deliberately deferred, not
  omitted by oversight; would need a baseline that actually clears the
  bar `docs/model_methodology.md` describes, which none currently do.
- **Incorporating sentiment/macro signals** -- no adapter exists yet
  (`docs/model_methodology.md`'s "what's not built yet").
- **A dashboard surfacing this** (spec section 21's UI requirements,
  Tahap 6) -- this is DB-only output today, no API endpoint or UI.
