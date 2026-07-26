# Technical features (Tahap 3)

Status: started. See `src/features/technical/indicators.py`,
`src/features/technical/market_relative.py`, and
`src/features/technical/pipeline.py` docstrings for full detail -- this is
a summary plus the real run results.

## What's computed

45 indicators per company/date, long-format in `technical_features`
(company_id, feature_date, feature_name, value, feature_set_version=`v2`):

- **Trend**: SMA 5/10/20/50/100/200, EMA 12/26, MACD + signal + histogram, ADX 14
- **Momentum**: RSI 14, Stochastic %K/%D, ROC 10, Williams %R 14, momentum return 5/20/60/120/252
- **Volatility**: Bollinger Bands 20 (upper/middle/lower/bandwidth), ATR 14, historical volatility 20/60, downside volatility 20
- **Volume/liquidity**: volume SMA 20, volume ratio 20, OBV, Accumulation/Distribution line, MFI 14, average daily traded value 20
- **Market-relative vs. IHSG** (`market_relative.py`, added 2026-07-25):
  `beta_60`/`beta_252` (rolling Cov(stock,market)/Var(market)),
  `alpha_60`/`alpha_252` (a **simplified excess-return proxy**, NOT CAPM
  alpha -- see limitation below), `relative_strength_5/20/60/120/252`
  (stock's momentum return minus IHSG's over the same window).

Implemented from scratch in pure pandas (spec 2.15-16: numeric computation
must be deterministic code this project validated itself, not a
third-party black box). Every function documents its exact convention --
e.g. RSI/ATR/ADX use Wilder's smoothing (`ewm(alpha=1/window)`), the
convention most charting platforms use; a naive SMA-based version would
disagree with those platforms' numbers.

Computed on **adjustment-scaled OHLC**: every price column multiplied by
`market_prices_clean.adjustment_factor`, so a stock split doesn't appear
as a fake one-day crash in a moving average.

## Known limitation: `alpha_*` is not CAPM alpha

Real CAPM alpha needs a risk-free rate, and this project has no verified
Indonesia-domestic risk-free-rate source (the same gap documented in
`docs/valuation.md`/`docs/macro_data.md` blocking DCF). `alpha_60`/
`alpha_252` here are a simplified proxy: `stock_return - beta *
market_return`, no risk-free rate subtracted. Never call this a true CAPM
alpha anywhere downstream, and never substitute `us_10y_treasury_yield`
(a US/global proxy, not Indonesia's own rate) into this calculation.

## Deferred, not overlooked

- **Support/resistance** (swing/fractal/pivot ensemble, Fibonacci from
  validated swings) is a separate, larger piece of work.
- **Turnover ratio** needs `shares_outstanding` on a per-date basis --
  what's available now (see `docs/market_data.md`'s market cap section)
  is a current snapshot, not a historical series.
- **Sector-relative features** (vs. a sector index rather than IHSG) --
  blocked on real sector classification data (`docs/data_sources.md`'s
  company-master-data limitation), same blocker as the recommendation
  engine's `investment_style` field.

## Real run results (2026-07-25)

Selection: top 50 companies by market cap (spec-adjacent proxy for "IHSG
constituents" -- there's no IHSG-membership data ingested, so market cap
rank is the closest available signal). Ranking required building a new
market cap module first -- see `docs/market_data.md`'s market cap section
for that, including a real ranking bug it caught (mega-caps silently
dropped due to a NULL close on today's still-forming bar).

`python -m src.cli features compute-technical --tickers BBCA,BREN,...`
(the real top 50, led by BBCA/BREN/DCII/BBRI/BMRI):

- **50/50 companies succeeded**, 0 skipped.
- **3,556,320 feature rows written** for this run (4,218,529 total in the
  table including an earlier 10-company proof-of-concept sample from
  before the ranking was built).
- 36 distinct feature names confirmed present per company, row counts per
  feature matching each company's actual price history length (e.g. BBCA:
  2,465 rows per feature, i.e. its full ~10-year history).

## Market-relative features: real run results (2026-07-25)

Once `docs/macro_data.md`'s IHSG series existed, the same top-50 set was
recomputed (`FEATURE_SET_VERSION` bumped `v1` -> `v2`):

- **50/50 companies succeeded**, 0 skipped, **4,282,156 total feature
  rows** (up from 3,556,320 -- the new 9 market-relative feature names
  account for the difference).
- All 9 market-relative feature names confirmed present:
  `beta_60`, `beta_252`, `alpha_60`, `alpha_252`,
  `relative_strength_5/20/60/120/252`.
- Spot-checked against BBCA: `beta_60=0.686`, `beta_252=0.745` --
  plausible for a large, comparatively stable bank stock (beta below 1).
  1,672 real `beta_60` rows (vs. 1,423 for `beta_252`, which needs more
  history to start producing values) -- consistent with "more history
  needed for a longer window," not a bug.

### Two real bugs found and fixed -- both in test fixtures, not the pipeline

Testing this against a live database surfaced two real calendar-alignment
bugs, both in synthetic test fixtures, not the production code:

1. A fixture using every **calendar day** (including weekends) produced
   an all-`NaN` `beta_60`/`alpha_60` -- `pct_change()` on a
   weekend-padded, IHSG-reindexed series NaNs out the day *after* every
   weekend gap too, so no 60-row window was ever fully clean enough for
   `rolling(60, min_periods=60)` to produce a value.
2. Fixing that to **weekdays-only** still failed -- real IDX trading
   calendars have real holidays (e.g. 2025-01-01 New Year) that a
   Mon-Fri-only fixture doesn't account for, leaving enough scattered
   gaps that, again, no 60-row window was ever fully clean.

Both were caught not by assuming the pipeline was right, but by running
it against **real BBCA production data** (whose own trading calendar
naturally matches IHSG's -- both are real IDX data) and confirming
`beta_60` computed a real, plausible value there. That proved the
pipeline logic itself was correct and the fixtures were wrong. Fixed by
building the test fixture's price dates directly from real
`ihsg_composite` observation dates already in the database, guaranteeing
zero artificial calendar mismatch
(`test_compute_technical_features_includes_market_relative_features`,
`src/tests/test_technical_pipeline.py`).

## CLI

```
python -m src.cli features compute-technical --offset 0 --limit 150
python -m src.cli features compute-technical --tickers BBCA,TLKM,ASII
```

Re-running for a company clears and rewrites its rows first (idempotent --
`technical_features` has no natural unique constraint on
`(company_id, feature_date, feature_name)` to upsert against, a Tahap 1
schema decision that didn't anticipate needing per-name upsert).
