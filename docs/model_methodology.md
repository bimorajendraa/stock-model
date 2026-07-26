# Model methodology (Tahap 4)

Status: baseline models only. No model here is promoted to serve
recommendations -- this documents what was actually built and what the
real (not simulated) results show, honestly, per spec section 18: "Jangan
menyatakan model bebas overfitting atau underfitting. Laporkan bukti
evaluasinya."

## Pipeline

```
build_labeled_dataset(session, tickers, horizons)
  -> technical_features (DB, long) pivoted wide, joined with point-in-time
     forward-return + direction labels, rows with no real outcome dropped
split_dataset(df, horizon_days, embargo_days)
  -> default_split_dates: ~65/15/20 calendar-date train/validation/test
  -> purge_and_split: removes rows whose label window crosses into the
     next split's embargo zone
run_baseline_comparison(session, tickers, horizon_days, embargo_days)
  -> fits every baseline on the same train split, evaluates all on the
     same validation/test splits
```

## Why date-based, not random, splitting

Spec sections 2.4 and 17 explicitly forbid random splits / random K-Fold
for time-series data. Splits here are calendar-date boundaries **shared
across every ticker** -- not a per-ticker row-count split. Tickers have
wildly different history lengths in the current dataset (AADI ~1.5 years,
BBCA ~10 years); a row-count split would let one ticker's "test" period
be, in calendar time, earlier than another ticker's "train" period --
exactly the kind of cross-sectional leakage this avoids.

**Embargo + purging**: a training row is only kept if its label window
(date -> date + horizon) doesn't reach into the embargo zone before the
next split. Returns are serially correlated day-to-day, so a naive
adjacent-boundary split would leak information across it.

## Labels

Point-in-time forward returns per horizon (5/20/60/120/252 trading days)
and a binary direction label, computed directly from `market_prices_clean`
close prices (`src/ml/datasets/labeling.py`). Deliberately narrower than
spec section 14's full wishlist -- see that module's docstring for what's
omitted and why (mainly: no IHSG/sector index series ingested yet, so
"beat IHSG" and sector-relative labels aren't computable without
fabricating a proxy).

## Baselines (spec section 13)

Every real model must clear these before being trusted (spec section 32):
`naive_base_rate` (predicts the training set's base rate for every row),
`moving_average_rule` (predicts "up" when close > SMA-20, a fixed-margin
rule, not learned), then `logistic_regression`, `random_forest`, and a
small `simple_mlp` (16 hidden units) -- all from scikit-learn, with
capacity limits and regularization per spec section 18
(`src/ml/baselines/sklearn_models.py`).

## Real results (2026-07-25)

Top 50 companies by market cap, 20-day horizon, embargo=10 days:
`n_train=51,101`, `n_validation=12,316`, `n_test=19,495`,
`train_positive_rate=0.487` (roughly balanced classes).

| Model | Train AUC | Val AUC | Test AUC | Train Bal.Acc | Val Bal.Acc | Test Bal.Acc |
|---|---|---|---|---|---|---|
| naive_base_rate | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 |
| moving_average_rule | 0.501 | 0.493 | 0.491 | 0.501 | 0.493 | 0.491 |
| logistic_regression | 0.547 | 0.525 | 0.518 | 0.531 | 0.516 | 0.512 |
| random_forest | 0.692 | 0.554 | 0.522 | 0.623 | 0.534 | 0.509 |
| simple_mlp | 0.649 | 0.527 | 0.530 | 0.606 | 0.511 | 0.530 |

### Honest reading of this table

- **The moving-average rule has no real edge** -- its AUC sits at/below
  0.5 on every split, meaning "price above its 20-day average" is not a
  useful signal for 20-day-forward direction in this dataset, despite
  being a common informal trading heuristic.
- **Random forest and the MLP show clear overfitting.** Random forest's
  train AUC (0.692) is far above its test AUC (0.522) despite
  `max_depth=6`/`min_samples_leaf=20` regularization; the MLP shows the
  same pattern (0.649 train vs. 0.530 test). This is reported as evidence,
  not hidden -- the regularization in place is not enough to close this
  gap, and would need tightening (fewer trees/shallower depth, stronger
  MLP weight decay) or more/better features before this gap is
  acceptable.
- **Logistic regression -- the most-regularized model -- has the smallest
  train/test gap (0.547 vs. 0.518) but also the weakest absolute signal.**
  This is the expected trade-off, not a contradiction.
- **None of the trained models robustly clear the spec section 32 quality
  gate** ("mengalahkan baseline pada metrik utama," stably, not on one
  lucky split). Test-set AUCs of 0.51-0.53 are only marginally above the
  0.50 random baseline, well within the range where a different random
  seed or a slightly different split boundary could flip the ranking.

### What this plausibly means, not just what it shows

This project's technical-only feature set (36 price/volume-derived
indicators, no fundamentals, no sentiment, no macro/sector context) is
probably close to its practical ceiling for 20-day-forward direction
prediction on IDX large caps. This is consistent with financial theory
(near-random-walk short/medium-term price action) and with the master
spec's own architecture (section 13's multi-branch design explicitly
expects technical + fundamental + sentiment + macro branches combined via
a meta-learner, not technical alone). **No model from this run is
promoted to production or referenced by any recommendation logic** --
none exist yet, and none would be justified by these results regardless.

## Fundamentals-augmented run (2026-07-25) -- honest negative result

Once `financial_ratios` existed (`docs/fundamentals.md`), the natural next
question was whether adding them changes the picture above.
`build_labeled_dataset(..., include_fundamentals=True)` attaches 13
`fund_*` ratio columns via a point-in-time as-of join (each trading day
gets the most recently *available* -- not most recent *period* -- ratio
value per company, verified leak-free by
`test_build_labeled_dataset_include_fundamentals_is_point_in_time`, which
plants a "future" statement and confirms it never appears before its own
`available_at`). Same top-50 universe, same horizon=20/embargo=10:

| | technical-only | technical+fundamental |
|---|---|---|
| n_features | 36 | 49 (36 + 13 fund_*) |
| n_train | 51,101 | 12,068 |
| n_validation | 12,316 | 1,890 |
| n_test | 19,495 | 1,205 |

**The dataset shrinks by ~76% (test set by ~94%) the moment fundamentals
are required**, because `financial_ratios.available_at` only goes back to
roughly 2022 (statements go back to `2021FY` at the earliest -- see
`docs/fundamentals.md`) while technical features go back to 2016. Every
row dated before a company's first available statement is correctly
dropped (spec section 2.12: no imputed placeholder), not a bug, but it
means this comparison is confounded from the start -- fewer independent
samples, a narrower and more recent time window, not a clean like-for-like.

| Model | Test AUC (technical-only) | Test AUC (+fundamental) | Train AUC (technical-only) | Train AUC (+fundamental) |
|---|---|---|---|---|
| naive_base_rate | 0.500 | 0.500 | 0.500 | 0.500 |
| moving_average_rule | 0.491 | 0.445 | 0.501 | 0.486 |
| logistic_regression | 0.518 | 0.523 | 0.547 | 0.625 |
| random_forest | 0.522 | 0.510 | 0.692 | 0.840 |
| simple_mlp | 0.530 | 0.548 | 0.649 | 0.781 |

### Honest reading -- this is a negative result, not a win

- **Random forest got strictly worse**: train AUC jumped to 0.840 (from
  0.692) while test AUC *dropped* to 0.510 (from 0.522). More features on
  a quarter of the data, with the same `max_depth=6`/`min_samples_leaf=20`
  regularization, produced more overfitting, not more signal.
- **Logistic regression and the MLP show a small test-AUC uptick**
  (0.518->0.523, 0.530->0.548) that **should not be read as fundamentals
  helping** -- the test set shrank to 1,205 rows, small enough that a
  0.01-0.02 AUC move is well within noise, and both models' train/test
  gap widened substantially (logistic: 0.547->0.625 train; MLP:
  0.649->0.781 train), the opposite of what "the extra features are
  genuinely useful" would look like.
- **The moving-average rule got worse too** (0.491->0.445) despite not
  using any fundamental feature at all -- pure evidence that the
  confound (smaller n, later/narrower date range) matters on its own,
  independent of whatever the fundamental features contribute.
- **No model here clears any bar that would justify calling fundamentals
  a real improvement.** The honest conclusion is that this specific
  integration (13 ratios, ~4 years of point-in-time coverage, from a
  single research-only provider) doesn't show a usable signal yet --
  most plausibly because the resulting sample is simply too small and
  too short a window for the added features to pay for themselves, not
  necessarily because fundamentals are uninformative in principle.

**No model from this run -- with or without fundamentals -- is promoted
to production or referenced by any recommendation logic.**

## Horizon experiment (2026-07-25) -- does a longer label horizon change anything?

The negative fundamentals result above raised a direct question: is a
20-day label just the wrong timescale for ratios like ROE/margin that
move slowly, and would fundamentals show a real contribution over a
horizon economically closer to how those numbers actually matter (months,
not weeks)? Rather than guess, `run_baseline_comparison` was re-run at
horizon_days = 60, 120, and 252 (embargo scaled proportionally,
`embargo_days = horizon_days // 2`), both technical-only and
technical+fundamental, same top-50 universe.

**Technical-only (no fundamentals) test-set AUC by horizon:**

| Model | h=20 | h=60 | h=120 | h=252 |
|---|---|---|---|---|
| naive_base_rate | 0.500 | 0.500 | 0.500 | 0.500 |
| moving_average_rule | 0.491 | 0.506 | 0.471 | 0.424 |
| logistic_regression | 0.518 | 0.520 | **0.559** | 0.461 |
| random_forest | 0.522 | 0.531 | 0.538 | 0.452 |
| simple_mlp | 0.530 | 0.513 | 0.554 | 0.393 |

**Technical+fundamental: could not be evaluated at h=120 or h=252 at
all** -- both runs errored with `"one or more splits are empty"`. Real
cause, visible in the returned split info: fundamentals only cover ~4
years, and once `horizon_days + embargo_days` (120+60=180 days,
252+126=378 days) is subtracted from an already-short window on both
ends of the train/validation/test boundary, there's no calendar space
left for a validation split at all (`n_validation=0`). At h=60 it did
run, but `n_test` collapsed to **1 row** -- functionally unusable
(several sklearn warnings about single-class test folds confirm this,
not a silent success).

### Honest reading

- **h=120's logistic regression (test AUC 0.559, train 0.588) is the
  single best result across every baseline run so far**, technical-only
  or combined, and has a comparatively small train/test gap -- worth
  noting, but this is one result out of 4 horizons x 5 models x 2 feature
  sets = 40 combinations tried across two sessions of experimentation.
  Picking the best cell after the fact is exactly the kind of
  horizon-shopping/multiple-comparisons risk spec section 18 warns
  against -- this is reported as "an interesting cell to watch," not as
  a discovered edge, and would need out-of-sample confirmation (a
  different date range, or a proper multiple-testing-corrected search)
  before being trusted.
- **h=252 (longest horizon, technical-only) is uniformly *worse than
  random* across every learned model** (0.39-0.46 test AUC, all below
  0.500) -- not just "no edge," but predictions that would have been
  actively wrong if acted on, during this particular test window
  (2025-2026). Plausible causes: a real regime shift between the
  training and test periods (252-day-forward IHSG conditions genuinely
  differ), or the effective sample size collapsing because adjacent
  daily rows over a 252-day label window overlap almost completely
  (highly autocorrelated, so the nominal row count overstates
  independent information). Both are real risks this project's
  methodology is designed to surface, not hide.
- **The fundamentals+long-horizon combination is not a "no signal"
  result -- it's a "not measurable with the data currently available"
  result.** This directly answers whether fundamentals need more testing
  before writing them off: they don't need a *longer label horizon* on
  the *current* history depth, they need *more historical statements*
  (the actual blocker is calendar coverage, not horizon choice) --
  already flagged in `docs/fundamentals.md`'s "not built yet" (a second
  provider or real-filing-date/XBRL source with deeper history).

### What this means for "should Tahap 3 be finished first"

This experiment is evidence against that being the highest-leverage next
step, at least in the form of "build the remaining Tahap 3 adapters, then
retrain": macro/industry/news adapters would add *new* branches, but
wouldn't fix either problem actually found here -- the fundamentals
branch is blocked by *history depth* (a data-acquisition problem, not a
feature-completeness one), and the technical-only ceiling looks
structural (near-random-walk short/medium-term price action, consistent
with financial theory) rather than something more features of the same
kind (macro regime, sentiment) are guaranteed to fix, though they remain
architecturally expected by the spec and untested here. Widening the
company universe from 50 to 944 would add more independent series
(helps variance/overfitting somewhat) but doesn't address either root
cause identified above.

## Mid-cap experiment (2026-07-25) -- is the ceiling mega-cap-specific?

A more targeted hypothesis than "widen to all 944 companies": IDX's top-50
by market cap are the most liquid, most analyst-covered stocks on the
exchange -- textbook efficient-market territory. Small/mid-cap stocks
with thinner analyst coverage are the classic place market-efficiency
theory (the "small-cap effect") predicts more exploitable mispricing.
Cheap to test with existing code (no new adapters, just point the same
pipeline at a different ticker slice): ranked all 926 companies with a
computed market cap, took ranks 201-250 (EPMT, ACES, WSKT, SMRA, BIRD,
GJTL, ...) -- real mid-caps at ~Rp4.0-6.3T market cap, roughly 8-19x
smaller than the top-50's cutoff (~Rp46T at rank 50), technical features
computed for real (3,364,985 rows, 50/50 companies; 3 had thin history --
WSKT 1 day, JECX 14 days, WBSA 74 days -- real trading-halt/data
characteristics, not errors), then the same technical-only baseline
comparison at horizon=20 and horizon=120 (the horizon that showed the
best mega-cap result).

| Model | h=20 mega-cap | h=20 mid-cap | h=120 mega-cap | h=120 mid-cap |
|---|---|---|---|---|
| naive_base_rate | 0.500 | 0.500 | 0.500 | 0.500 |
| moving_average_rule | 0.491 | 0.489 | 0.471 | 0.469 |
| logistic_regression | 0.518 | 0.517 | **0.559** | 0.485 |
| random_forest | 0.522 | 0.532 | 0.538 | 0.532 |
| simple_mlp | 0.530 | 0.518 | 0.554 | 0.556 |

### Honest reading

- **At h=20, mid-cap and mega-cap results are essentially
  indistinguishable** across every model (differences of 0.001-0.010 AUC,
  well within noise). No small-cap edge showed up.
- **The h=120 mega-cap "best result so far" (logistic regression, 0.559)
  did NOT replicate on mid-caps (0.485 -- actually below random)** --
  this is exactly the out-of-sample check flagged as needed when that
  result was first reported, and it failed to hold up. Treat the earlier
  0.559 as noise from testing many horizon/model combinations, not a real
  edge, now with direct evidence rather than just a theoretical caution.
  Random forest and the MLP, by contrast, land at nearly the same test
  AUC on both samples at h=120 (0.538 vs. 0.532, 0.554 vs. 0.556) --
  consistent, unremarkable, no edge either way.
- **The small-cap-effect hypothesis is not supported by this dataset.**
  Company size/liquidity tier (at least mega-cap vs. this mid-cap band)
  doesn't change the picture -- both sit in the same ~0.47-0.56 AUC band
  regardless of horizon or model. This is one mid-cap band (ranks
  201-250) tested once, not an exhaustive sweep across all size tiers --
  but it directly weighs against "the ceiling is a top-50-specific
  efficiency artifact."

### Where this leaves "what's the best next step"

Three independent angles have now been tested against the technical-only
ceiling -- more features (fundamentals, negative), longer horizons (mixed
and mostly negative), different market-cap tier (negative) -- without
finding a robust edge. This is meaningfully stronger evidence for a
structural ceiling (technical/near-term price action genuinely carries
little exploitable signal on this exchange, consistent with market
efficiency theory) than any single result on its own would be. It does
**not** prove new *kinds* of information (macro regime, news/sentiment --
still unbuilt) wouldn't help; those remain the spec's own expected
architecture and haven't been tested at all yet. But it does mean neither
"finish Tahap 3's remaining scope for this branch" nor "just add more
companies" is likely to be the unlock on their own.

## What's not built yet

- Sentiment/macro feature branches (need macro/news adapters -- not
  built, spec section 3.4/3.6/13.2/13.4). Fundamental ratios now exist
  (see above) but don't yet show a usable signal in this dataset size.
- Gradient boosting baselines (XGBoost/LightGBM/CatBoost, spec section 13)
  -- deferred, not because they're expected to fix the overfitting issue
  above, but to avoid adding a heavy dependency before there's a reason
  to believe it changes the conclusion.
- Meta-learner / ensemble (spec section 13.5) -- premature: two branches
  (technical, fundamental) exist, but the fundamental branch doesn't yet
  show a usable signal on its own to combine.
- Triple-barrier labeling, 3-year/5-year scenario horizons (spec section
  14-15) -- current horizons (5/20/60/120/252 days) cover the shorter end
  only.
- Calibration, walk-forward re-training, champion/challenger promotion
  (spec sections 18, 23) -- no model here is a "champion" to challenge.
