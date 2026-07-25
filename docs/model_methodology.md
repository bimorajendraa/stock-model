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

## What's not built yet

- Fundamental/sentiment/macro feature branches (need fundamentals/macro/
  news adapters -- not built, spec section 3.3-3.6/13.2-13.4).
- Gradient boosting baselines (XGBoost/LightGBM/CatBoost, spec section 13)
  -- deferred, not because they're expected to fix the overfitting issue
  above, but to avoid adding a heavy dependency before there's a reason
  to believe it changes the conclusion.
- Meta-learner / ensemble (spec section 13.5) -- premature with only one
  branch (technical) actually built.
- Triple-barrier labeling, 3-year/5-year scenario horizons (spec section
  14-15) -- current horizons (5/20/60/120/252 days) cover the shorter end
  only.
- Calibration, walk-forward re-training, champion/challenger promotion
  (spec sections 18, 23) -- no model here is a "champion" to challenge.
