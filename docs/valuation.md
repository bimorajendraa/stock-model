# Valuation (Tahap 5, spec section 8/10)

Status: one method implemented and verified against real data --
**self-relative (own-history) multiple valuation** (`src/valuation/relative.py`,
`src/valuation/pipeline.py`), writing into the `valuation_results` table
that already existed from the Tahap 1 schema. Peer/sector-relative
valuation and DCF are **not** built yet -- see "Why self-relative first"
below for the real, current blockers.

## What's computed

For each company, using only real data already in the database (no
external assumption):

- **P/E method**: latest reported diluted EPS (fallback basic) x the
  25th/50th/75th percentile of that company's own historical P/E ratio
  (`financial_ratios`, annual + quarterly combined) = bear/base/bull fair
  value.
- **P/B method**: same idea with the latest `book_value_per_share` ratio
  and the company's own historical P/B percentile range.
- Both methods need >= 3 historical data points and a positive per-share
  metric to run -- fewer points would make a percentile look falsely
  precise, and a non-positive EPS/book-value-per-share makes the
  multiple conventionally meaningless (same convention already used for
  P/E in `docs/fundamentals.md`'s ratio computation). Not computable is
  recorded as not-applicable, never a fabricated number.
- When both methods are available, the final bear/base/bull is an
  equal-weight average of the two; `fair_value_conservative` is the
  **minimum** bear-case estimate across methods (a lower bound to anchor
  on, not something smoothed toward the middle).
- `sensitivity` (JSONB) records every component number that went into the
  estimate (percentiles, point counts, latest EPS/BVPS, the market price
  and its date at computation time) -- full audit trail, not just the
  final number.

## Why self-relative first, not peer/sector-relative or DCF

- **Peer/sector-relative** needs `sector_registry`/
  `companies.sector_registry_id` populated -- still NULL for essentially
  every company (`docs/data_sources.md`: no verified free IDX
  sector-classification source found yet). Comparing a bank's P/E to a
  miner's would be worse than not comparing at all.
- **DCF** needs a discount rate, which needs a real risk-free-rate proxy
  (BI-Rate or similar) -- no macro adapter exists yet
  (`docs/model_methodology.md`'s "what's not built yet"). A valuation is
  extremely sensitive to the discount rate; guessing one would be exactly
  the kind of fabricated assumption spec section 2.12 forbids.
- **Self-relative** needs no external assumption at all -- every input
  (historical P/E/P/B series, latest EPS/book-value-per-share) is a real,
  already-computed, point-in-time value already sitting in
  `financial_ratios`/`financial_statement_items` from the fundamentals
  work (`docs/fundamentals.md`).

## Known limitations -- stated plainly, not hidden

- This answers **"is this cheap or expensive relative to its OWN past,"
  not "intrinsic value"** in the DCF sense. Two real caveats on top of
  that:
  - The comparison is partly circular: the historical P/E/P/B series is
    itself built from past *market prices*, which already reflect
    whatever sentiment/risk re-rating happened over that window -- not a
    price-independent fundamental anchor.
  - The window is short: this project's fundamentals history is only
    ~4 years deep (`docs/fundamentals.md`), so the percentile range may
    just reflect whatever market regime occurred in those 4 years, not a
    stable long-run range.
- `data_quality_score` is a simple 0-1 completeness heuristic
  (`min(1.0, (n_pe_points + n_pb_points) / 16)`), not a rigorous
  statistical confidence score -- don't read more precision into it than
  that.

## Real run results (2026-07-25)

`python -m src.cli valuation compute --tickers <top-50-by-market-cap>`
(same 50-company set as the rest of Tahap 3/4/5):

- **50/50 companies succeeded**, 0 skipped.
- **42/50 used both P/E and P/B methods; 8 fell back to P/B-only**
  (TPIA, MPRO, SRAJ, CDIA, EMAS, MDKA, GOTO, EXCL) -- companies with a
  non-positive or too-short EPS history, correctly excluded from the P/E
  method rather than producing a meaningless negative or fabricated
  multiple.
- `data_quality_score` ranged 0.25-0.94 across the set (median 0.94) --
  most companies have enough of both methods' history; a handful (like
  GOTO, a comparatively recent IPO) have shorter P/B-only history and a
  correspondingly lower score.
- Spot-checked against real current prices: BBCA's base fair value sits
  close to its current price (-8.8%); TLKM and ASII show larger gaps
  (-24.3%, -28.4%, i.e. current price above their own historical median
  multiple); GOTO and MDKA show the opposite (current price below their
  own historical median). All directionally sensible given each
  company's real recent history, not fabricated-looking numbers.

## Idempotency

Unlike `technical_features`/`financial_ratios` (fully recomputed,
"current knowledge" tables), `valuation_results` is meant to accumulate a
real history of point-in-time snapshots as this is run on different
days -- idempotency is scoped to *that day's* row only (re-running today
replaces today's row; a snapshot computed yesterday is untouched). Both
behaviors verified by
`test_compute_valuation_is_idempotent_per_day_not_across_days`.

## CLI

```
python -m src.cli valuation compute --tickers BBCA,TLKM,ASII
python -m src.cli valuation compute --offset 0 --limit 150
```

## What's not built yet

- **Peer/sector-relative valuation** -- blocked on real sector
  classification data (see above).
- **DCF** -- blocked on a real discount-rate input (macro adapter, see
  above).
- **Recommendation engine** (spec section 21) that would combine this
  valuation output with the Tahap 4 model outputs (currently showing no
  usable edge, `docs/model_methodology.md`) and eventual
  sentiment/macro signals into a single labeled recommendation
  (`recommendation_results` table exists from Tahap 1, unused).
- **Scenario-based valuation** (3-year/5-year bear/base/bull per spec
  section 14-15) -- current bear/base/bull are multiple-percentile
  scenarios for *today*, not multi-year forward scenarios.
