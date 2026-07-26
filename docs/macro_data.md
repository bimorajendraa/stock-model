# Macro / industry-wide series (Tahap 3.4 branch)

Status: two adapters implemented and verified against real data --
`YahooFinanceMacroAdapter` (FX/global-yield/index/commodity, research-only)
and `BPSMacroAdapter` (real Indonesia national inflation, documented-free
with a registered API key). Covers 5 real series. Real BI-Rate is still
not covered -- see "What was actually investigated" below for exactly
why, not a vague "not done yet."

## What was actually investigated (2026-07-25)

Checked live before writing any code (spec section 2.2: never a
fabricated/guessed source):

- **BPS (Statistik Indonesia) Web API** (`webapi.bps.go.id`) -- real,
  documented, free, and does cover inflation -- **now integrated**, using
  a real API key the user registered and provided (`BPS_API_KEY` in
  `.env`, `study-only` registration). See `bps.py`'s section below for
  what it actually returns.
- **Bank Indonesia's own site** (`bi.go.id`) -- BI-Rate (BI 7-Day Reverse
  Repo Rate) is published there, but checked live: HTML-only, a
  press-release table with no JSON/API/RSS endpoint. Scraping that page
  would be exactly the kind of programmatic-access-outside-intended-use
  case spec section 2.5-6 is cautious about -- same reasoning that
  already excluded Stooq's JS-gated CSV download
  (`docs/data_sources.md`). Excluded, not worked around. **Still not
  covered by any adapter.**
- **yfinance** -- already trusted (research_only) for OHLCV/fundamentals
  -- also has real, live, keyless FX and index/commodity tickers.
  Verified live: `USDIDR=X` (USD/IDR spot), `^JKSE` (IHSG), `^TNX` (US
  10-Year Treasury yield), `CL=F` (WTI crude) all return real, current,
  plausible values. Guessed tickers for an Indonesian government bond
  yield and Brent crude (`ID10YT.B`, `BRENTOIL=F`) both correctly 404'd
  -- not silently substituted with something else.

## BPS adapter (`src/data_sources/macro/bps.py`) -- what it actually covers

Real, national, monthly inflation (month-over-month), verified live:

- Endpoint chain: subject catalog (`sub_id=3` = "Inflasi") -> variable
  catalog (`var_id=1` = "Inflasi Bulanan (M-to-M)") -> data endpoint,
  filtered to `vervar=9999` ("INDONESIA", the national aggregate row
  inside an otherwise per-city breakdown table called "Kota Inflasi").
- `var_id=2` ("Indeks Harga Konsumen (Umum)", the CPI index level) was
  also checked but turned out to be a **discontinued series** -- its own
  `th` (year) list tops out at 2019. Deliberately excluded rather than
  serving stale data or guessing a successor variable ID.
- **Two real bugs found and fixed, both live, both real API/response
  constraints, not code logic errors**:
  1. BPS caps the `th` (year range) request parameter at **3 years
     max** -- found via a real error message
     ("The maximum allowed number of years for the 'th' parameter is
     3"). Fixed by chunking the requested range into <=3-year windows.
  2. `datacontent` response keys are
     `{vervar}{var_id}{turvar}{th_val}{turtahun_val}` concatenated with
     **no separator** -- decoded by cross-referencing the same
     response's own `tahun`/`turtahun` label lists (`th_val = calendar_
     year - 1900`, confirmed against the real `th` list for 2017-2026).
- `available_at` is a genuine per-point estimate here (not a shared
  batch "now") -- see "Point-in-time correctness" below.

## Known limitations, stated plainly

- `us_10y_treasury_yield` is a **global/US** rate-environment proxy, **not
  Indonesia's own risk-free rate or BI-Rate**. It does **not** resolve the
  "no real discount-rate input for DCF" gap noted in `docs/valuation.md`.
- BPS's inflation series is the **only** real Indonesia-domestic macro
  series covered. Real BI-Rate itself is still not available from any
  adapter (see above) -- inflation alone is not a substitute for a
  discount-rate input.

## Point-in-time correctness: a real bug found and fixed across BOTH adapters

Building the BPS adapter's per-point `available_at` (a real formula:
end-of-month + 10 days, erring toward BPS's real ~1-2-day publication
lag, never earlier -- same safe-direction discipline as
`docs/fundamentals.md`) made a pre-existing gap in the **Yahoo** adapter
obvious by contrast: it fetches years of backfill in one call but only
ever set one **batch-level** `available_at=now` for every point --
meaning a 2016 USD/IDR observation was being stamped as only having
become available *today*. Not a hypothetical: `ingest_macro_series`
copied that single batch value onto every row. Fixed in both places:
`SeriesPoint` now carries an optional per-point `available_at`; the Yahoo
adapter sets a same-day-close estimate (`observation_date + 1 day`,
appropriate for daily market data's real same-day publication); the BPS
adapter sets its own real monthly-lag estimate; `ingest_macro_series`
prefers the per-point value, falling back to the batch value only when a
provider doesn't set one.

## Series and table routing

Three destination-table-relevant series definitions live in
`src/data_sources/macro/taxonomy.py`'s `SERIES_CATALOG` (the model
docstrings draw the macro vs. industry distinction: "economy-wide
series" vs. "market-wide series ... not tied to a single company"):

| series_code | table | Provider | Real value (2026-07-24/25) |
|---|---|---|---|
| `usdidr_fx` | `macro_series` | Yahoo | ~17,935 IDR/USD |
| `us_10y_treasury_yield` | `macro_series` | Yahoo | ~4.68% |
| `id_inflation_mom` | `macro_series` | BPS | 0.44% (June 2026) |
| `ihsg_composite` | `industry_series` | Yahoo | ~6,196 points |
| `wti_crude_oil` | `industry_series` | Yahoo | ~$89.31/bbl |

Both destination tables already had a real unique constraint from the
Tahap 1 schema (`series_code`, `observation_date`, `source_id`) -- unlike
most of this project's other tables, ingestion here is a genuine
`ON CONFLICT` upsert, not clear-then-rewrite (verified by
`test_ingest_macro_series_upserts_updated_value`).

## Real run results (2026-07-25)

`python -m src.cli macro sync` (full history since 2016-01-01, matching
the OHLCV backfill window; each series routed to whichever adapter
actually declares it in `supported_series()`):

- **5/5 series succeeded**, 0 skipped.
- Yahoo series: `usdidr_fx` (2,749 points), `us_10y_treasury_yield`
  (2,653 points), `ihsg_composite` (2,547 points), `wti_crude_oil`
  (2,654 points) -- all 2016-2026 daily history.
- BPS series: `id_inflation_mom` -- **126 real monthly points,
  2016-01-31 to 2026-06-30** (fetched across 4 chunked <=3-year API
  calls), each with a real per-point `available_at` (e.g. April 2026's
  observation -> available_at 2026-05-11).

## Why this matters beyond "one more data source"

`ihsg_composite` unblocked a real, previously-deferred gap:
`docs/technical_features.md` had listed "market-relative features (beta,
alpha, relative strength vs. IHSG)" as deferred for lack of an index
series. **That feature is now built** -- see
`docs/technical_features.md`'s market-relative section for the real run
results and two more real bugs (calendar-alignment ones, in test
fixtures) found building it.

## CLI

```
python -m src.cli macro sync                          # all 5 known series, full history, routed per-adapter
python -m src.cli macro sync --series ihsg_composite   # one series only
python -m src.cli macro sync --series id_inflation_mom # BPS only
```

## What's not built yet

- **Real BI-Rate** -- Bank Indonesia's own site is HTML-only, no API
  found live; not covered by any adapter (see above).
- **A second macro provider** (redundancy) -- not started.
- **Feeding macro series into valuation (DCF) or the recommendation
  engine** -- `us_10y_treasury_yield` is deliberately NOT used as a
  BI-Rate substitute (see limitation above); `id_inflation_mom` alone
  isn't a discount-rate input either. A real Indonesia-domestic rate
  would still be needed first.
