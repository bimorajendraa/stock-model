# Data sources

Status: Tahap 2 -- market-data adapters, capability-aware provider
selection, and real ingestion implemented and verified against live data
(81,709 real OHLCV rows across 49 companies, see below); one fundamentals
adapter implemented and verified (see `docs/fundamentals.md`); one macro
adapter implemented and verified for FX/global-yield/index/commodity
series (see `docs/macro_data.md` -- real Indonesia-specific series like
BI-Rate/BPS inflation are a documented gap, not silently worked around);
industry (per-sector metrics)/news adapters not started. This documents
the category
structure and access-tier policy adapters must follow (spec §3, §2.5-10).
It intentionally does not name specific vendor endpoints/URLs until an
adapter for them is actually implemented and reviewed against their terms
of use -- listing an unverified endpoint here would violate the "never
fabricate a source" rule as much as fabricating data would.

## Access-tier policy (`AccessType`, `src/data_sources/base.py`)

1. **official** -- IDX itself, government/regulatory bodies (e.g. Bank
   Indonesia for BI-Rate, BPS for inflation/GDP), or a company's own
   disclosures.
2. **documented_free** -- a provider with a published, programmatic-use-
   permitting API/feed (open data portals, RSS, documented free-tier APIs).
3. **fallback_provider** -- anything else, used only as a cross-check or
   gap-filler, never as the sole source for a given fact (spec §2.9).

Every concrete adapter must declare which tier it is in
`data_source_registry.access_type` and must not scrape in violation of
robots.txt, ToS, auth walls, paywalls, or CAPTCHAs (spec §2.5-6) -- if a
source requires that, it is out of scope for this project, not a "find a
workaround" problem (`TermsOfServiceViolation` in
`src/data_sources/base.py` is the hard-stop signal for this case).

## Categories and interfaces

| Category | Interface | Spec section | Adapter count requirement |
|---|---|---|---|
| Market data (OHLCV, corporate actions) | `src/data_sources/market/base.py::MarketDataProvider` | §3.2 | >=2 adapters -- **done**: `twelve_data.py`, `sectors_app.py`, `yahoo_finance.py` (research-only fallback) |
| Fundamentals (financial statements) | `src/data_sources/fundamentals/base.py::FundamentalsProvider` | §3.3 | official-first structured chain implemented: authorized IDX XBRL archive + Yahoo research fallback; official coverage awaits a configured archive |
| Macro (BI-Rate, inflation, FX, global macro) | `src/data_sources/macro/base.py::MacroDataProvider` | §3.4 | one per publisher -- **1 of 2+ done**: `yahoo_finance.py` (research-only, FX/global-yield/IHSG/commodity only, see `docs/macro_data.md`) |
| Industry/sector-specific metrics | filing taxonomy + `src/features/sector/disclosed.py` | §3.5 | bank NPL/NIM/CAR/LDR/CASA and mining reserve/production/cost metrics implemented; rows require disclosed filing facts |
| News | `src/data_sources/news/base.py::NewsProvider` | §3.6 | 5 domains in research mode, 4 production-safe; see `docs/news.md` |

## Market data: what was actually investigated (2026-07-24)

Before implementing anything, real candidate sources were checked live
(not recalled from memory -- spec §2.2 forbids fabricated endpoints).
Findings, so this isn't re-investigated from scratch later:

- **IDX's own site (idx.co.id)** blocks automated access outright -- even
  `robots.txt` returns 403 (Cloudflare bot protection). Programmatic access
  exists only via the paid "IDX Data Services" commercial product. Not
  usable as a free/scraped source; excluded.
- **Stooq** now gates its CSV download behind a JS proof-of-work challenge.
  Solving that programmatically would be exactly the kind of anti-bot
  bypass spec §2.5-6 prohibits. Excluded.
- **Yahoo Finance / `yfinance`** (`src/data_sources/market/yahoo_finance.py`)
  scrapes an undocumented endpoint outside Yahoo's ToS-sanctioned API --
  legally gray. Implemented anyway, on explicit user instruction, strictly
  scoped as a research/dev-only fallback: every row is tagged
  `usage_restriction=research_only` and it is refused outright in
  production mode (`MarketDataProviderSelector`, spec section 15 guardrail).
  See `docs/provider_capabilities.md`.
- **Twelve Data** (`src/data_sources/market/twelve_data.py`) -- real,
  documented REST API, genuinely free to register (confirmed via live
  error message, not marketing copy). `GET /stocks?exchange=IDX` returns
  real IDX tickers even with the public `demo` key (947 instruments synced
  into the database, verified live: 942 equities + 5 indices).
  `GET /time_series` needs a real (still free)
  key, and a capability probe (`src/data_sources/market/capability.py`)
  actually checks whether that key's plan covers XIDX before trusting it
  -- never assumes "key present" means "usable." access_type:
  `documented_free`. Corporate actions endpoint NOT implemented -- its
  contract wasn't verified before this was written, so it's left as
  `NotImplementedError` rather than guessed.
- **Twelve Data's own `/stocks` listing mixes asset types**: five records
  are indices (`I.GRADE`, `IDXBUMN20`, `IDXHIDIV20`, `IDXSMC.COM`, and
  `IDXSMC.LIQ`), not tradable equities. Three have no Yahoo Finance series;
  two do have usable market history. They are retained as real master
  records with `asset_type=index`, while default equity pipelines exclude
  them. Explicit ticker selection remains an operator override.
- **Sectors.app** (`src/data_sources/market/sectors_app.py`) -- IDX-focused,
  implemented directly against the live OpenAPI schema at
  `https://api.sectors.app/schema/` (docs.sectors.app itself 403s automated
  fetches, but the schema endpoint doesn't). No free tier -- inert until
  `SECTORS_APP_API_KEY` is set. access_type: `fallback_provider`. Known
  real limitation: `/v2/daily/{symbol}/` returns close/volume/market_cap
  only, no open/high/low -- the adapter returns `None` for those rather
  than fabricating them. Also exposes a large fundamentals/sector-metrics
  surface (`/v2/companies/` supports SQL-like queries over revenue, ROE,
  banking NPL/NIM/CAR, etc.) -- worth prioritizing when
  `FundamentalsProvider`/`IndustryProvider` adapters are built, since one
  verified vendor covering both saves re-doing this research.
- **Sectors.app's v1 API is dead**: a v1 endpoint found via search-engine
  snippets returned `410 Gone` (sunset 2026-05-11) when actually queried --
  confirms why every endpoint here was checked live instead of trusted from
  search results or memory.

Both implemented adapters raise `ProviderUnavailableError` (not a crash,
not fabricated data) when their API key is absent or the upstream call
fails -- ingestion code must catch this and fall back per spec §33.

## Company master data ("data master saham", spec §3.1)

Neither market-data adapter returns sector, subsector, listing date,
listing board, or free float in a bulk-friendly way:

- Twelve Data's `/stocks` gives ticker + name + a coarse instrument type.
- Sectors.app's `/v2/companies/` screener supports filtering/sorting on
  those richer fields but, per its own schema (`CompanyScreenerItem`),
  only *returns* `symbol` + `company_name` per row -- getting the rest
  would mean one `/v2/company/report/{symbol}/` call per company (1 API
  credit each), impractical without a paid key.

So `MarketDataProvider.list_companies()` (both adapters) and
`src/ingestion/company_sync.py` are intentionally thin: they sync
ticker + name + normalized `asset_type`, and never touch
sector/subsector/listing_date/etc. --
those columns stay `NULL` rather than being guessed. A real "data master
saham" source (properly IDX itself, or another official registry) is
still needed for that data; company_sync only unblocks
`ingest_ohlcv`'s FK requirement in the meantime. Verified live
end-to-end on 2026-07-24: 947 real IDX instruments synced from Twelve Data
into the local database. A later classification audit identified 942
equities and 5 indices; sync remains idempotent on re-run.

`company_sync.sync_companies` never deletes or delists a company just
because one provider call didn't mention it (spec §3.1 survivorship-bias
rule) -- it only adds new tickers and updates names or asset types of
existing ones.

## OHLCV backfill: real results (2026-07-25)

Full universe backfilled, not just a sample: `python -m src.cli market
backfill --offset N --limit 150`, run in 7 sequential chunks to keep each
process run bounded in time (see ADR-style rationale in the commit that
added `--offset`/`--limit`), no fixtures, real Yahoo Finance data
(Twelve Data's `demo` key can't fetch prices, only listings -- see
`docs/provider_capabilities.md`):

- **All 942 equities succeeded**. Two indices (`IDXBUMN20` and
  `IDXHIDIV20`) also had usable history, producing 944 covered instruments;
  the other three indices had no Yahoo Finance series. See the
  company-master asset-type note above.
- **1,706,497 OHLCV rows written**, spanning 2016-07-25 to 2026-07-24 (the
  10-year backfill window; many tickers have shorter real history because
  they IPO'd more recently -- e.g. AADI only goes back to 2024-12-05).
- **104 bars quarantined** across the full run (real inconsistent OHLC in
  the source data -- e.g. `high < open` -- correctly caught by
  `validate_ohlcv_bar` rather than written to `market_prices_raw`).
- Idempotency verified on the initial 10-ticker smoke test before the full
  run: re-running the same window produced zero row-count growth and
  updated one bar's values in place. The full 944-instrument run reuses the
  identical upsert code path.
- Two real bugs were found and fixed by this process before the full run
  (see the "test: add live market ingestion smoke test" commit): a 32-bit
  volume column overflow, and a Postgres 65535-bound-parameter limit hit
  by a single large multi-row INSERT. Both required actually running
  against real data to discover -- fixtures wouldn't have caught either.

## Macro/industry-wide series: what was actually investigated (2026-07-25)

Full account in `docs/macro_data.md` -- summary here for the same
"checked live, not from memory" discipline as the market-data
investigation above:

- **BPS Web API** (real, documented, free, covers inflation/CPI) --
  needs a registered API key this project doesn't have. Documented gap,
  not worked around.
- **Bank Indonesia's site** (BI-Rate) -- HTML-only, no API/RSS found
  live. Excluded, same reasoning as Stooq's JS-gated download below.
- **yfinance** -- real, keyless data for `USDIDR=X` (FX), `^JKSE`
  (IHSG), `^TNX` (US 10Y yield, a *global* proxy, explicitly NOT a
  BI-Rate substitute), `CL=F` (WTI crude). Implemented; run for real:
  10,603 points across 4 series, 2016-2026 daily history.

## News source weighting (spec §3.6)

Adapters tag `credibility_tier` 1-6 on ingestion (1 = regulator/official
disclosure, 6 = blog/opinion). Syndicated copies of the same story across
multiple portals do not count as independent confirmation --
deduplication (`news_articles.is_duplicate`, `duplicate_of_id`,
`cross_source_confirmed`) happens in `features/sentiment/` (Tahap 3).

## What happens when coverage is thin

If fewer than 5 news domains are found for a company, the platform must
report the actual count and mark `cakupan berita terbatas` -- it must never
fabricate additional articles to hit the target (spec §3.6). Same principle
applies platform-wide: missing data renders as `data tidak mencukupi`
(`ValidationStatus.INSUFFICIENT`), never a guessed value (spec §2.12).
