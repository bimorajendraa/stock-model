# Macro / industry-wide series

Status: **6 real adapters**, 13 series, verified against real data and
persisted for real (2026-07-26): `YahooFinanceMacroAdapter` (FX/global-
yield/index/commodity, research-only), `BPSMacroAdapter` (Indonesia
national inflation), `BankIndonesiaRateHTMLAdapter` (real BI-Rate, HTML-
scraped), `BankIndonesiaJISDORAdapter` (real USD/IDR JISDOR reference
rate), `BankIndonesiaSEKIInterestRateAdapter` (real Deposit/Lending
Facility rates, parsed from a real legacy-Excel download), `WorldBankMacroAdapter`
(GDP growth, unemployment -- research/cross-check), `FREDMacroAdapter`
(US Fed Funds, dollar index -- code-complete, not yet live-verified, no
API key registered).

**Real BI-Rate is now covered.** The earlier "HTML-only, no API, excluded"
conclusion (see below) was correct that no JSON API exists, but wrong to
stop there -- "no JSON API" and "blocked" are not the same thing (this
project's own rule). Revisited with the goal of scraping the real HTML
table instead of treating its absence as a wall.

## What was actually investigated (2026-07-25, superseded below)

Checked live before writing any code (spec section 2.2: never a
fabricated/guessed source):

- **BPS (Statistik Indonesia) Web API** (`webapi.bps.go.id`) -- real,
  documented, free, and does cover inflation -- integrated using a real
  API key the user registered and provided (`BPS_API_KEY` in `.env`).
- **Bank Indonesia's own site** (`bi.go.id`) -- BI-Rate is published
  there, checked live: HTML-only, no JSON/API/RSS endpoint. **At the
  time, this was treated as a reason to exclude it entirely** -- revised
  below once actually asked to scrape it for real.
- **yfinance** -- real, live, keyless FX and index/commodity tickers
  (`USDIDR=X`, `^JKSE`, `^TNX`, `CL=F`).

## Bank Indonesia HTML adapters (`src/data_sources/macro/bi_rate.py`, `bi_seki.py`)

Real, official, server-rendered HTML/legacy-Excel data -- verified with a
bare `curl` before writing any parser (no JavaScript execution needed;
`robots.txt` checked and allows all three paths used).

**BI-Rate** (`bi_rate.aspx`) and **JISDOR** (`jisdor/default.aspx`):
table columns parsed directly (Indonesian date format "22 Juli 2026",
rate as "5.75 %" or Indonesian-formatted currency "Rp17.973,00").
Real pagination is **ASP.NET WebForms postback** (`__doPostBack`,
`__VIEWSTATE`/`__VIEWSTATEGENERATOR`/`__EVENTVALIDATION` hidden fields),
not a `?page=N` query string -- found by inspecting the raw HTML before
writing the pagination code, followed exactly as a real browser click
would (not a bypass -- `robots.txt` already allows this path). Depth
capped at 5 pages (a real, disclosed limit, not full history): ~4 years
for BI-Rate's monthly-ish cadence, ~2 months for JISDOR's daily one.

**SEKI table I.25** (`ekonomi-keuangan/seki`): a real legacy `.xls` file
(verified with `file`: "Composite Document File V2 ... Creating
Application: Microsoft Excel", not a redirect/error page), containing
Bank Indonesia's own **Deposit Facility** and **Lending Facility**
rates -- the real standing-facility corridor around BI-Rate, directly
useful for `docs/valuation.md`'s discount-rate work later, not just a
macro curiosity. A `SEKIDatasetDiscoveryAdapter` also parses the real
~108-table SEKI catalog (section, table number, description, real `.xls`/
`.pdf` URLs) -- discovery covers the full catalog; a value-parser exists
for table I.25 only today, a real, disclosed scope limit.

### Three real bugs found live building the BI adapters

1. **Duplicate `href` attribute**: every PDF/XLS link on the SEKI catalog
   page has `href="https://.../X.xls" href="#"` -- invalid HTML.
   BeautifulSoup's `html.parser` resolves duplicates to the *last* one
   ("#"), silently discarding the real URL, and re-serializing the parsed
   tag (`str(tag)`) doesn't recover it either (the real value is already
   gone from the parse tree). Fixed by regexing the real URLs out of the
   *raw* response text directly and matching them positionally against
   the row sequence, not by inspecting the parsed tag's attributes.
2. **Missing `<tr>` wrapping**: the catalog's `<td>` cells for each table
   row are not wrapped in their own `<tr>` at all (only the section
   `<th>` headers are) -- `html.parser` doesn't synthesize the missing
   rows the way a browser would. Fixed by walking `<th>`/`<td>` elements
   in document order and chunking data cells in groups of 4 instead of
   relying on a row element.
3. **Year-header misalignment in the SEKI interest-rate table**: the year
   *value* in the wide table's header row is not reliably at its block's
   first column -- verified live: 2024's label sat at "Jan" (correct),
   but 2025's sat at "Dec" (its block's *last* populated column) and
   2026's at "Jun" (its most recent column so far). A naive "year label
   marks the block start" parser produced **duplicate (year, month)
   keys**, which crashed the real `ON CONFLICT` upsert
   (`psycopg.errors.CardinalityViolation: ON CONFLICT DO UPDATE command
   cannot affect row a second time`) -- caught by actually running the
   full sync, not by code review. Fixed by anchoring year-block
   boundaries on the month row's own "Jan" markers (verified reliable
   across every block checked) instead of the year row's position.

## World Bank / FRED (`world_bank.py`, `fred.py`) -- research/cross-check fallbacks only

Both explicitly **never override** BPS/BI's faster, more current national
series (registered after them in `cmd_macro_sync`'s provider list, and
their series codes don't overlap). **World Bank**: real, free, keyless
`api.worldbank.org/v2` -- verified live (GDP growth, unemployment,
annual frequency, `null` values for not-yet-published years correctly
excluded, never fabricated as 0). **FRED**: built strictly against its
own documented JSON contract (each observation's `value` is a *string*;
a not-yet-published value is the literal string `"."`, both real,
documented FRED conventions) -- **not live-verified**, since FRED
requires a registered key for every request and none was available.
Registered as `unverified` in `docs/data_source_registry.md` rather than
falsely claimed `healthy`; `cmd_macro_sync` degrades gracefully
(`ingest_macro_series` already catches `ProviderUnavailableError` and
prints a skip line, doesn't crash) when `FRED_API_KEY` isn't set.

## Known limitations, stated plainly

- `us_10y_treasury_yield`/FRED's US series are **global/US** rate-
  environment proxies, **not Indonesia's own risk-free rate**.
- BI-Rate/JISDOR/SEKI history depth is capped (see above) -- not full
  history, a real and disclosed limit.
- SEKI: only 1 of ~108 real cataloged tables has a value-parser.
- SDDS/INDONIA pages were checked live (both `healthy` in
  `docs/data_source_registry.md`'s audit) but have no adapter yet --
  discovery-only for now, a real remaining gap, not silently claimed done.

## Point-in-time correctness

Every adapter here sets a real, adapter-specific per-point `available_at`
(never a shared batch "now" -- a real bug found and fixed across the
Yahoo/BPS adapters early on, see git history): BI-Rate/JISDOR use the
observation date's own end-of-day (BI announces same-day); SEKI/World
Bank/FRED use a conservative fixed lag past the observation date/period-end,
since none of these expose a real per-observation publish timestamp.

## Series and table routing

`src/data_sources/macro/taxonomy.py`'s `SERIES_CATALOG`:

| series_code | table | Provider | Real value (2026-07-26) |
|---|---|---|---|
| `usdidr_fx` | `macro_series` | Yahoo | ~17,935 IDR/USD |
| `us_10y_treasury_yield` | `macro_series` | Yahoo | ~4.68% |
| `id_inflation_mom` | `macro_series` | BPS | 0.44% (June 2026) |
| `bi_rate` | `macro_series` | Bank Indonesia (HTML) | 5.75% (July 2026) |
| `usdidr_jisdor` | `macro_series` | Bank Indonesia (HTML) | ~17,973 IDR/USD |
| `id_gdp_growth_annual` | `macro_series` | World Bank | 5.11% (2025) |
| `id_unemployment_rate_annual` | `macro_series` | World Bank | 3.24% (2025) |
| `us_fed_funds_rate` | `macro_series` | FRED | not yet live-verified (no key) |
| `us_dollar_index_broad` | `macro_series` | FRED | not yet live-verified (no key) |
| `bi_lending_facility_rate` | `macro_series` | Bank Indonesia (SEKI) | 6.5% (June 2026) |
| `bi_deposit_facility_rate` | `macro_series` | Bank Indonesia (SEKI) | 4.75% (June 2026) |
| `ihsg_composite` | `industry_series` | Yahoo | ~6,196 points |
| `wti_crude_oil` | `industry_series` | Yahoo | ~$89.31/bbl |

## Real run results (2026-07-26)

`python -m src.cli macro sync` (full history since 2016-01-01):

- **11/13 series succeeded, 11,041 total points**; 2 skipped
  (`us_fed_funds_rate`, `us_dollar_index_broad` -- no `FRED_API_KEY`
  configured, a graceful, disclosed skip, not a crash).
- BI-Rate: 50 real decisions, 2022-07-21 to 2026-07-22 (5 pages).
- JISDOR: 14 real daily rates (5 pages, ~2 months given daily frequency).
- World Bank: 10 points each for GDP growth and unemployment (2016-2025).
- SEKI: **114 points each** for Lending Facility and Deposit Facility,
  2017-2026 -- spot-checked for economic plausibility: Lending Facility
  is always above Deposit Facility on the same date (the real BI standing-
  facility corridor), verified programmatically in
  `test_bi_seki_adapter_live.py`, not just eyeballed.
- BPS: 126 points, re-verified after `docs/data_source_registry.md`'s
  audit found the earlier claim of this had gone stale (see that doc for
  the full account) -- confirmed reproducible, not a code bug.

## Why this matters beyond "one more data source"

`ihsg_composite` unblocked `docs/technical_features.md`'s market-relative
features (beta/alpha/relative strength vs. IHSG). The new BI-Rate/SEKI
series are a real, disclosed step toward `docs/valuation.md`'s still-open
"no real Indonesia discount-rate input for DCF" gap -- not yet wired into
valuation, but the raw data no longer needs to be sourced from scratch.

## CLI

```
python -m src.cli macro sync                            # all known series, full history, routed per-adapter
python -m src.cli macro sync --series bi_rate            # BI-Rate only
python -m src.cli macro sync --series usdidr_jisdor      # JISDOR only
python -m src.cli macro sync --series bi_lending_facility_rate,bi_deposit_facility_rate  # SEKI only
```

## What's not built yet

- **SDDS/INDONIA value-parsers** -- pages checked live and `healthy`, no
  adapter yet.
- **Full SEKI breadth** -- 1 of ~108 real cataloged tables covered.
- **FRED live verification** -- code-complete, needs a registered
  `FRED_API_KEY` (free) to actually confirm against a real response.
- **Feeding macro series into valuation (DCF) or the recommendation
  engine** -- the real BI-Rate/SEKI data needed for a real Indonesia
  discount rate now exists, but isn't wired into `docs/valuation.md` yet.
