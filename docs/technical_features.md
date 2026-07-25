# Technical features (Tahap 3)

Status: started. See `src/features/technical/indicators.py` and
`src/features/technical/pipeline.py` docstrings for full detail -- this is
a summary plus the real run results.

## What's computed

36 indicators per company/date, long-format in `technical_features`
(company_id, feature_date, feature_name, value, feature_set_version):

- **Trend**: SMA 5/10/20/50/100/200, EMA 12/26, MACD + signal + histogram, ADX 14
- **Momentum**: RSI 14, Stochastic %K/%D, ROC 10, Williams %R 14, momentum return 5/20/60/120/252
- **Volatility**: Bollinger Bands 20 (upper/middle/lower/bandwidth), ATR 14, historical volatility 20/60, downside volatility 20
- **Volume/liquidity**: volume SMA 20, volume ratio 20, OBV, Accumulation/Distribution line, MFI 14, average daily traded value 20

Implemented from scratch in pure pandas (spec 2.15-16: numeric computation
must be deterministic code this project validated itself, not a
third-party black box). Every function documents its exact convention --
e.g. RSI/ATR/ADX use Wilder's smoothing (`ewm(alpha=1/window)`), the
convention most charting platforms use; a naive SMA-based version would
disagree with those platforms' numbers.

Computed on **adjustment-scaled OHLC**: every price column multiplied by
`market_prices_clean.adjustment_factor`, so a stock split doesn't appear
as a fake one-day crash in a moving average.

## Deferred, not overlooked

- **Market-relative features** (beta, alpha, relative strength vs.
  IHSG/sector) need an index price series -- no macro/industry adapter
  ingests one yet.
- **Support/resistance** (swing/fractal/pivot ensemble, Fibonacci from
  validated swings) is a separate, larger piece of work.
- **Turnover ratio** needs `shares_outstanding` on a per-date basis --
  what's available now (see `docs/market_data.md`'s market cap section)
  is a current snapshot, not a historical series.

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

## CLI

```
python -m src.cli features compute-technical --offset 0 --limit 150
python -m src.cli features compute-technical --tickers BBCA,TLKM,ASII
```

Re-running for a company clears and rewrites its rows first (idempotent --
`technical_features` has no natural unique constraint on
`(company_id, feature_date, feature_name)` to upsert against, a Tahap 1
schema decision that didn't anticipate needing per-name upsert).
