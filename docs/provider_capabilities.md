# Provider capabilities

Status: Tahap 2. This documents the multi-provider capability system for
market data OHLCV -- the rule it exists to enforce is: **an API key
existing does not mean the endpoint can be used.** A provider's free/basic
plan is not guaranteed to include Indonesia Stock Exchange (XIDX) data, and
the only way to know is to actually call the endpoint and inspect the
response, not just check for HTTP 200.

## The three providers

| Provider | Role | Official IDX source? | Commercial use? |
|---|---|---|---|
| Twelve Data | Company reference (proven working) + optional paid OHLCV | No -- third-party vendor | Not reviewed; treated as `unspecified`, never assumed |
| Yahoo Finance (`yfinance`) | Research/dev OHLCV fallback | No -- explicitly unofficial | Never -- refused in production mode |
| IDX (idx.co.id) | Would be the official source | Yes | N/A -- not reachable (see below) |

**IDX itself is not usable by this project.** idx.co.id blocks automated
access outright -- even `robots.txt` returns 403 (Cloudflare bot
protection). Programmatic access exists only through the paid "IDX Data
Services" commercial product. Every place in this codebase that mentions
"IDX verification" (reconciliation, corporate-action confirmation) means
*cross-provider* verification instead, and says so explicitly -- never
silently substitutes something else while claiming it's IDX.

## Capability probe (Twelve Data)

`src/data_sources/market/capability.py::probe_twelve_data_ohlcv_capability`
actually calls `/time_series` for one real IDX ticker pulled from the
database (never a hardcoded symbol) and classifies the response:

| Status | Meaning |
|---|---|
| `available` | Real OHLCV values came back |
| `invalid_key` | Key missing/wrong/demo-only (verified live: the public `demo` key classifies here) |
| `plan_restricted` | Key is real but the plan doesn't cover this market/endpoint |
| `rate_limited` | HTTP 429 / rate-limit message |
| `capability_probe_required` | No `TWELVE_DATA_API_KEY` configured at all |
| `error` | Anything else (network failure, unexpected shape, etc.) |

**Honesty note on `plan_restricted`**: this project never had a real
(non-demo) Twelve Data key to test against, so that specific response
shape was never observed live -- classification for it is inferred from
Twelve Data's general documented conventions (HTTP 403 / message keywords
like "plan", "subscribe", "upgrade"), not verified. If a real key's
restricted-plan response doesn't match this pattern, it currently falls
through to the generic `error` status rather than being silently
misclassified as something else -- tighten `classify_twelve_data_error`
once a real restricted-plan response is observed.

A real bug was caught by live-testing this probe rather than trusting a
mocked response: Twelve Data's actual demo-key error has no `"status"`
key at all (`{"code": 401, "message": ...}`), which the original adapter's
`payload.get("status") == "error"` check silently missed entirely. Fixed
in `src/data_sources/market/twelve_data.py` and
`capability.is_twelve_data_error_payload`.

## Selection logic (`MARKET_DATA_PROVIDER=auto`)

`src/data_sources/market/selector.py::MarketDataProviderSelector.select()`:

1. Probe Twelve Data (unless a specific provider is forced via config).
2. If `available` -> use it. Log the selection either way (spec: "Jangan
   fallback secara diam-diam tanpa mencatat provider yang digunakan").
3. If not available and `MARKET_DATA_USAGE_MODE=production` -> raise
   `NoLicensedProviderAvailableError`. Production mode never silently uses
   a research-only provider.
4. If not available, mode is `research`, and
   `ENABLE_YAHOO_FINANCE_FALLBACK=true` -> fall back to Yahoo Finance,
   logged as a warning (`market_data_provider_fallback`), tagged
   `usage_restriction=research_only`.
5. Otherwise -> raise `ProviderAccessError`.

Verified live (2026-07-25): with `TWELVE_DATA_API_KEY=demo`, the probe
correctly classifies the response as `invalid_key` and the selector
correctly falls back to `yahoo_finance`, with both steps logged.

## Usage restriction tagging

Every row written to `market_prices_raw` carries `usage_restriction`:

- `yahoo_finance` rows -> always `research_only`.
- `twelve_data` rows -> `unspecified` (not `licensed`) -- this project has
  not reviewed Twelve Data's plan-level commercial-redistribution terms,
  so it does not claim licensing it hasn't verified.

## Production guardrail

`MARKET_DATA_USAGE_MODE=production` refuses Yahoo Finance outright (raises
rather than silently ingesting research-only data) and requires an
available, capability-confirmed licensed provider. Dashboard-facing badges
(`RESEARCH DATA`, `LICENSED DATA`, `STALE DATA`, `UNVERIFIED CORPORATE
ACTION`) are not yet built (no dashboard exists yet -- Tahap 6) but the
underlying `usage_restriction`/`verification_status` columns they'd read
from already exist.
