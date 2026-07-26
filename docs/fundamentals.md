# Fundamentals (financial statements, Tahap 3.3 + 8 branches)

Status: one adapter implemented and verified against real data --
`YahooFinanceFundamentalsAdapter` (`src/data_sources/fundamentals/yahoo_finance.py`),
same `research_only` status as the existing Yahoo Finance OHLCV adapter --
plus deterministic ratio computation (spec section 8) on top of it
(`src/features/fundamentals/{ratios,pipeline}.py`). See "Ratio computation"
below for what's covered and the real bug this step's own follow-up audit
caught.

## What was actually investigated (2026-07-25)

Before writing any adapter code, `yfinance` was checked live against two
real IDX tickers with structurally different reporting (spec section 3.5
warns fundamentals structure varies by sector):

- **BBCA.JK** (bank) -- `income_stmt`/`balance_sheet`/`cashflow` all real,
  `financialCurrency=IDR`, FY2025 net income ~Rp57.5T matches the publicly
  known figure. As expected for a bank, it reports no `Cost Of Revenue`/
  `Gross Profit`/current-asset-liability split -- correctly **omitted**,
  never fabricated as zero.
- **TLKM.JK** (non-bank) -- has the "standard" `Cost Of Revenue`/
  `Gross Profit`/`EBITDA`/current-assets structure BBCA lacks, confirming
  the sector-dependent shape is real, not a BBCA-specific quirk.

Both annual (`income_stmt` etc., ~4-5 fiscal years back) and quarterly
(`quarterly_income_stmt` etc., ~5 quarters back) statements are available
and are genuinely discrete-quarter figures, not year-to-date cumulative
(cross-checked: BBCA's four 2025 quarterly net-income figures sum to
approximately its FY2025 annual figure).

## Known limitation: `available_at` is an estimate, not a filed date

This is the most important caveat in this document, so it's stated
plainly: **yfinance does not expose the real public-disclosure date for
any statement** -- only the fiscal `period_end`. Spec section 3.3 forbids
treating those as the same date (a Q4 statement is not "available" the
moment the quarter ends -- it isn't filed for weeks or months).

Since no real filing-date source is integrated yet, `available_at` here is
a **conservative estimate**:

- Annual statements: `period_end + 120 days`
- Quarterly statements: `period_end + 60 days`

Both deliberately upper-bound real BEI/OJK filing deadlines (POJK
29/2016: audited annual FS due within 120 days of FY-end; BEI Peraturan
I-E: interim reports due within 30-60 days of quarter-end). Erring long is
the *safe* direction for point-in-time correctness -- **under**estimating
`available_at` is the actual leakage risk (a model "seeing" a number
before it was real-world-public); **over**estimating only means
conservatively under-using very recent data, never leakage. The estimate
basis is recorded in `financial_statements_raw.raw_payload` so nothing
downstream mistakes it for a real filed date.

**If a real filing-date source is ever integrated (e.g. IDX's own
disclosure system, or a vendor that captures actual submission
timestamps), this estimate must be treated as inferior and replaced, not
merged or averaged with it.**

## Standardized account taxonomy

`src/data_sources/fundamentals/taxonomy.py` defines 30 provider-agnostic
`account_code`s across `income_statement`/`balance_sheet`/`cash_flow`,
covering the inputs spec section 8's core ratios need (margins, ROE/ROA,
current ratio, DER, EPS/PER/PBV) -- deliberately a small, high-value
subset, not an exhaustive taxonomy. The Yahoo adapter's field-name mapping
(`_YAHOO_FIELD_NAMES` in `yahoo_finance.py`) is asserted at import time to
cover exactly this taxonomy, so a drift between the two fails loudly, not
silently.

A company's statement that doesn't report a given account_code (e.g. a
bank's `cost_of_revenue`) simply has no row for it -- never backfilled
with a fabricated `0` or interpolated value (spec section 2.12/6.3).

## Real run results (2026-07-25)

`python -m src.cli fundamentals sync --tickers <top-50-by-market-cap>`
(same 50-company set as `docs/technical_features.md`, led by
BBCA/BREN/DCII/BBRI/BMRI):

- **50/50 companies succeeded**, 0 skipped.
- **461 statements written** (203 annual, 258 quarterly) -- 9-10 statements
  per company (4-5 fiscal years annual + 4-5 recent quarters), matching
  what `yfinance` actually exposes rather than a fixed target.
- **11,909 line items written** across all statements -- averages ~26
  items/statement, ranging as low as ~18-21/statement for banks (BBCA,
  BBRI, BBNI, BRIS, BNLI, MEGA -- missing the non-bank-only accounts like
  `cost_of_revenue`/`current_assets`, as expected) up to ~28-29 for
  non-banks with fuller reporting (ADRO, HMSP, UNVR).
- **CDIA is the sparsest company** (7 statements, 148 items) -- it's a
  recent IPO (Chandra Daya Investasi), so `yfinance` simply has less
  history for it; correctly reflected as fewer real rows, not padded to
  match its peers.

## Completeness-based quality_status (found and fixed during a follow-up audit)

Auditing the first run turned up a real gap: 14 of the 461 statements had
only 1-3 line items populated out of the 30-code taxonomy (vs. ~20-29 for
a normal statement), but were all stamped `quality_status=VALID` alongside
fully-populated ones -- misleading for anything consuming this table
downstream (e.g. a ratio calculator silently computing a "ratio" off a
statement that's 90% missing). Two real, reproducible causes:

- **Oldest column in Yahoo's rolling window** (`2021FY`/older annuals,
  some `2025Q3` quarters depending on the ticker) -- Yahoo often carries
  one more period than it has full data for.
- **Q4 standalone figures not separately disclosed** (`TLKM 2024Q4`,
  `EXCL 2024Q4`) -- common in Indonesian reporting; only cumulative FY and
  discrete Q1-Q3 are filed, so Q4-alone is genuinely thin data, not a bug.

Fix: `ingest_fundamentals` now computes `completeness = len(line_items) /
30` per statement and marks it `QualityStatus.INSUFFICIENT`
(`data_tidak_mencukupi`) below a 20% threshold, on **both** the raw
statement and its items -- the real numbers are still written (never
dropped; a company with 2 real values is still 2 more real values than
none), just correctly flagged so downstream code can filter on
`quality_status` instead of trusting every row equally.
`raw_payload` also now records `n_items`/`completeness_ratio` per
statement for auditability.

Re-running the full 50-company sync after this fix: same 461
statements/11,909 items (idempotent, no data lost), now split **447
VALID / 14 INSUFFICIENT** -- exactly the 14 statements identified above,
confirming the fix targets precisely the real gap and nothing else.
Covered by `test_sparse_statement_is_marked_insufficient_not_dropped` and
`test_complete_enough_statement_is_marked_valid`
(`src/tests/test_ingestion_fundamentals.py`), using a fake provider so the
test doesn't depend on which real period happens to be sparse on Yahoo's
live data at test time.

## Idempotency

No natural unique constraint exists on `financial_statements_raw` or
`financial_statement_items` (a statement's real identity is
company+statement_type+fiscal_period, not enforced at the DB level yet).
Same pattern as `technical_features`: re-syncing a company clears every
existing statement (and its items) for that company, then rewrites from
the provider's current answer -- verified by a real rerun producing an
identical statement count, not a growing one
(`test_ingest_fundamentals_is_idempotent_on_rerun`).

## Ratio computation (spec section 8)

`src/features/fundamentals/ratios.py` computes 13 ratios deterministically
in Python (spec section 2.15: an LLM must never compute a ratio directly)
from a statement's own line items -- `gross_margin`, `operating_margin`,
`net_margin`, `roe`, `roa`, `debt_to_equity`, `debt_to_assets`,
`current_ratio`, `fcf_margin`, `ocf_margin`, `book_value_per_share`, plus
two price-dependent ones, `price_to_earnings` and `price_to_book`. A
deliberately small, high-value subset (same philosophy as the 30-code
account taxonomy), not spec section 8's full wishlist.

`src/features/fundamentals/pipeline.py` (`compute_fundamental_ratios`)
writes every ratio for every usable statement into `financial_ratios`:

- Only statements with `quality_status != INSUFFICIENT` are used -- a
  statement already flagged too thin to trust shouldn't feed a ratio that
  then *looks* confidently computed.
- **Every** ratio is written per statement, applicable or not
  (`is_applicable=False`, `value=None` when a bank has no computable
  `current_ratio`) -- never a dropped row, matching
  `FinancialRatio.is_applicable`'s own documented purpose.
- `price_to_earnings`/`price_to_book` look up the company's own
  `market_prices_clean` close **on/before** the statement's
  `available_at` date -- point-in-time correct, never a later price
  (verified live by `test_price_dependent_ratios_use_point_in_time_price`,
  which plants a price the day before `available_at` and a decoy price
  the day after, and asserts only the earlier one is used).
- `ratio_name` is suffixed `__annual`/`__quarterly` because an annual and
  its Q4 quarterly statement commonly share the same `period_end`, and
  `financial_ratios` has no separate statement-type column -- without the
  suffix, two ratios from two different reporting granularities would
  collide on (company_id, ratio_name, period_end).

CLI: `python -m src.cli features compute-fundamental-ratios --tickers BBCA,TLKM`.

### Real run results (2026-07-25)

Same top-50 set: **50/50 companies, 5,811 ratio rows, 5,278 applicable
(90.8%)** -- the ~9% not-applicable is mostly bank
`gross_margin`/`operating_margin`/`current_ratio` (sector-structural, not
a bug) plus `price_to_earnings` for loss-making periods. Sanity-checked
against BBCA's real, most recent annual figures: `net_margin=50.3%`,
`roe=20.4%`, `price_to_book=2.56x`, `price_to_earnings=12.5x` -- all
consistent with BBCA's well-known position as IDX's highest-ROE,
premium-valued major bank; `gross_margin`/`operating_margin`/
`current_ratio` correctly `is_applicable=False` (bank statement structure).

### Real bug found and fixed during this step's own follow-up audit

Testing this step end-to-end surfaced a genuine data-destroying bug, not
just a logic bug: `src/tests/test_ingestion_fundamentals.py`'s tests
called `ingest_fundamentals` directly against the **real** `BBCA` company
row (to verify real Yahoo data), and their cleanup unconditionally
deleted *every* statement for that `company_id` afterward. Running the
integration suite after the real 50-company production sync silently
wiped BBCA's real statements back to zero -- caught by re-querying the DB
before moving on, not by the tests themselves (all of them still passed;
they were testing behavior correctly, just against the wrong company
identity). Fixed by giving those tests a disposable fixture `Company`
(fake ticker) with the adapter's `symbol_resolver` overridden to the real
`BBCA.JK` symbol -- real data is still fetched and verified, but the row
it's written to and deleted from is never the production one. BBCA's real
statements were then re-synced and re-verified identical (9 statements,
matching the pre-incident count) before ratios were computed for it.
Lesson generalized: any integration test that calls a clear-then-rewrite
ingestion function against a *real* ticker's `Company` row is destructive
by construction and must use a disposable fixture company instead
(`src/tests/test_technical_pipeline.py` and `test_market_cap.py` already
followed this pattern for their own tables; this file didn't, until now).

## What's not built yet

- **A second fundamentals provider** (spec section 3.3 implies redundancy
  the same way market data has Twelve Data + Yahoo Finance). Sectors.app's
  `/v2/companies/` screener (see `docs/data_sources.md`) already exposes a
  fundamentals-adjacent surface and is a reasonable next candidate --
  deferred because it has no free tier, same reason it's unused for market
  data reconciliation.
- **XBRL/real-filing-date source** -- see the `available_at` limitation
  above. Would also resolve `auditor_opinion`/`going_concern_flag`
  (currently always `None`/`False` -- yfinance doesn't expose either).
- **Feeding these features into the Tahap 4 ML pipeline** --
  `docs/model_methodology.md` documents that the current baselines use
  technical features only; fundamentals-derived features are a candidate
  for the next training run once ratios exist.
