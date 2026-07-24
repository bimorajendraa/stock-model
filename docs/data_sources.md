# Data sources

Status: Tahap 2 in progress -- market-data adapters implemented; fundamentals/
macro/industry/news adapters not yet started. This documents the category
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
| Market data (OHLCV, corporate actions) | `src/data_sources/market/base.py::MarketDataProvider` | §3.2 | >=2 adapters -- **done**: `twelve_data.py`, `sectors_app.py` |
| Fundamentals (financial statements) | `src/data_sources/fundamentals/base.py::FundamentalsProvider` | §3.3 | prioritize XBRL/structured over PDF/OCR |
| Macro (BI-Rate, inflation, FX, global macro) | `src/data_sources/macro/base.py::MacroDataProvider` | §3.4 | one per publisher |
| Industry/sector-specific metrics | `src/data_sources/industry/base.py::IndustryDataProvider` | §3.5 | one per sector where disclosed |
| News | `src/data_sources/news/base.py::NewsProvider` | §3.6 | target >=5 distinct domains per company analysis, cap ~10 |

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
- **Yahoo Finance / `yfinance`** scrapes an undocumented endpoint outside
  Yahoo's ToS-sanctioned API. Free and IDX-complete, but legally ambiguous
  -- not implemented (see ADR discussion in the Tahap 2 conversation; may
  be revisited if the user explicitly accepts that ambiguity).
- **Twelve Data** (`src/data_sources/market/twelve_data.py`) -- real,
  documented REST API, genuinely free to register (confirmed via live
  error message, not marketing copy). `GET /stocks?exchange=IDX` returns
  964 real IDX tickers even with the public `demo` key (verified live).
  `GET /time_series` needs a real (still free) key. access_type:
  `documented_free`. Corporate actions endpoint NOT implemented -- its
  contract wasn't verified before this was written, so it's left as
  `NotImplementedError` rather than guessed.
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

- Twelve Data's `/stocks` gives ticker + name only.
- Sectors.app's `/v2/companies/` screener supports filtering/sorting on
  those richer fields but, per its own schema (`CompanyScreenerItem`),
  only *returns* `symbol` + `company_name` per row -- getting the rest
  would mean one `/v2/company/report/{symbol}/` call per company (1 API
  credit each), impractical without a paid key.

So `MarketDataProvider.list_companies()` (both adapters) and
`src/ingestion/company_sync.py` are intentionally thin: they sync
ticker + name only, and never touch sector/subsector/listing_date/etc. --
those columns stay `NULL` rather than being guessed. A real "data master
saham" source (properly IDX itself, or another official registry) is
still needed for that data; company_sync only unblocks
`ingest_ohlcv`'s FK requirement in the meantime. Verified live
end-to-end on 2026-07-24: 947 real IDX companies synced from Twelve Data
into the local database, idempotent on re-run (0 created/updated second
time).

`company_sync.sync_companies` never deletes or delists a company just
because one provider call didn't mention it (spec §3.1 survivorship-bias
rule) -- it only adds new tickers and updates names of existing ones.

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
