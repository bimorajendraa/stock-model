# Corporate actions

Status: Tahap 2 -- provisional multi-source ingestion only. Nothing in
`corporate_actions` is officially verified yet (see "What's missing"
below).

## Data model

`corporate_actions` is a **multi-source log**, not a single source of
truth: every provider's report of a real-world event is its own row, keyed
by `(company_id, action_type, ex_date, source_provider)`.

- Re-running ingestion for the *same* provider updates that provider's row
  in place (idempotent -- proven by
  `test_ingest_same_source_rerun_updates_not_duplicates`).
- Two *different* providers reporting the same event never overwrite each
  other -- both rows are kept (proven by
  `test_ingest_different_sources_never_overwrite_each_other`). If BBCA's
  2025-12-03 dividend comes back as Rp55 from one source and Rp56 from
  another, both rows exist; nothing here decides which one is "right."

`action_type` values: `cash_dividend`, `stock_dividend`, `stock_split`,
`reverse_split`, `rights_issue`, `bonus_share`, `ticker_change`, `merger`,
`spin_off`.

## Verification status

Every row has `verification_status`:

- `provider_reported` -- what every row from this project's ingestion gets
  today. A single vendor said so; nothing more.
- `single_source` / `officially_verified` / `source_conflict` / `rejected`
  -- reserved for a confirmation workflow that does not exist yet.

**What's missing**: an actual process that cross-checks a
`provider_reported` action against IDX's own keterbukaan informasi (or
another official disclosure) and promotes it to `officially_verified`, or
flags `source_conflict` when two providers disagree materially. idx.co.id
blocking automated access (see `docs/data_sources.md`) is the same
obstacle here as for OHLCV reconciliation -- this needs either a manual
review step or a different official/documented source, neither of which
is built yet.

**Consequence**: nothing downstream (dividend yield calculations,
split-adjusted price series) should treat a `provider_reported` corporate
action as certain. `src/common/price_adjustment.py`'s
`internally_verified_adjusted` policy deliberately only uses
`officially_verified` splits for exactly this reason -- and currently has
nothing to compute from, since nothing has reached that status yet.

## Provider coverage

- **Yahoo Finance** (`src/data_sources/market/yahoo_finance.py`): real
  dividends and splits, verified live against BBCA -- cross-checked
  against Sectors.app's independently-documented example (same
  2025-12-03/Rp55 dividend, same 2021-10-13 1:5 split). All rows tagged
  `verification_status=provider_reported`.
- **Twelve Data**: NOT implemented. Its splits/dividends endpoint
  contract was never verified against a live response, and the spec
  forbids guessing API contracts -- `TwelveDataMarketProvider.
  get_corporate_actions` raises `NotImplementedError` with that reasoning
  rather than a guessed implementation.
- **Sectors.app** (`src/data_sources/market/sectors_app.py`):
  implemented against the live OpenAPI schema
  (`/v2/company/corporate-actions/{symbol}/`), but untested against a real
  response -- no API key was available (no free tier).

## CLI

```
python -m src.cli corporate-actions sync --ticker BBCA
```
