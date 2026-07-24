# Market data (OHLCV)

Status: Tahap 2. See `docs/provider_capabilities.md` for provider
selection logic and `docs/data_sources.md` for what was investigated
before building any of this.

## Pipeline

```
MarketDataProviderSelector.select(probe_ticker)
  -> (provider, capability)
ingest_ohlcv(session, provider, ticker, start, end, capability, run_id)
  -> provider.get_ohlcv() [with retry, spec section 10]
  -> validate_ohlcv_bar() per bar
       valid   -> upsert into market_prices_raw (with full lineage)
       invalid -> insert into market_price_quarantine (never dropped)
```

## What's stored, and why raw/adjusted/lineage are separate

`market_prices_raw` columns beyond plain OHLCV:

- `adjusted_close_provider` -- the provider's own adjusted close (e.g.
  yfinance's "Adj Close"). **Never overwrites** `close`, `open`, `high`,
  `low` -- those four are always exactly what the provider returned raw.
- `provider_adjustment_status` -- what kind of adjustment the provider
  applied (e.g. `provider_split_and_dividend_adjusted` for Yahoo).
- `provider_symbol`, `exchange`, `interval` -- the exact symbol/exchange/
  granularity used for this fetch (e.g. `BBCA.JK`, `IDX`, `1day`).
- `usage_restriction` -- `research_only` (Yahoo Finance, always) or
  `unspecified` (Twelve Data -- see `docs/provider_capabilities.md` for
  why this is never claimed `licensed`).
- `verification_status` -- `provider_reported` until a reconciliation run
  updates it to `reconciled_matched`/`reconciled_mismatch` for that
  specific row (see `docs/data_sources.md`'s reconciliation section).
- `adjustment_source`, `ingestion_run_id` -- which provider supplied the
  adjusted value (if any), and which `pipeline_runs.run_uuid` wrote this
  row, for tracing.

See `docs/risk_and_limitations.md` and `src/common/price_adjustment.py`
for the three-tier raw/provider-adjusted/internally-adjusted price model
and `PRICE_ADJUSTMENT_POLICY`.

## Validation and quarantine

`src/validation/market_data.py::validate_ohlcv_bar` checks: `high >=
open/close/low`, `low <= open/close`, all prices `> 0`, `volume >= 0`, and
`trade_date` not in the future. A field being `None` (e.g. today's
still-forming bar before market close) is **not** a validation failure --
that's a freshness concern (`src/common/trading_calendar.py`), handled
separately.

Bars that fail land in `market_price_quarantine` with the specific error
list, the provider, the raw row, and the `ingestion_run_id` -- never
silently dropped, never written to `market_prices_raw`.

## A real bug the volume column had

`market_prices_raw.volume` and `market_prices_clean.volume` were
originally 32-bit `INTEGER` (max ~2.1 billion). The Tahap 2 smoke test hit
`psycopg.errors.NumericValueOutOfRange` live on the second ticker -- some
IDX stocks trade daily volumes past that limit. Fixed by migrating both
columns (and `market_data_reconciliation.volume_difference`) to
`BIGINT`. Left here as a record of a real failure the live smoke test
caught that a fixture-based test would not have (no fixture author would
think to test a 2.1-billion-share day).

## Backfill vs. incremental update

`src/ingestion/incremental.py`:
- `backfill_window(listing_date)`: `start = max(10 years ago, listing_date)`,
  `end = latest completed trading day`. Falls back to 10 years flat if
  `listing_date` is unknown (neither adapter currently populates it --
  see `docs/data_sources.md`'s company-master-data limitation).
- `update_window(last_stored_date, ...)`: `start = last_stored_date -
  overlap (default 5 days)`, so a provider revising a recent bar after
  close still gets picked up without re-pulling years of history.

## Freshness

`src/common/trading_calendar.py::freshness_status` classifies the most
recent stored bar against `latest_expected_trading_day`: `fresh` /
`awaiting_eod` / `provider_delayed` / `stale`. Does not model IDX public
holidays (no citable official holiday API found) -- weekends are the only
modeled exclusion; a 1-3 trading-day tolerance before `stale` absorbs an
unmodeled holiday without misreporting it as a data failure.

## CLI

```
python -m src.cli providers check
python -m src.cli market smoke-test --count 10
python -m src.cli market backfill --count 50
python -m src.cli market backfill --ticker BBCA
python -m src.cli market update
python -m src.cli market reconcile --count 5
```

All commands record a `pipeline_runs` row and return a non-zero exit code
on failure.

## Rate limiting, retry, circuit breaker

`src/ingestion/resilience.py`: exponential backoff + jitter (capped
attempts, never retries permission errors like an invalid key -- a retry
can't fix that), a fixed-delay pacer between provider calls
(`OHLCV_REQUEST_DELAY_SECONDS`), and a circuit breaker that stops calling
a provider for the rest of a batch after consecutive failures rather than
timing out through an entire ticker list one by one.
