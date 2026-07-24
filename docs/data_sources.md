# Data sources

Status: Tahap 1 -- no adapters are implemented yet. This documents the
category structure and access-tier policy adapters must follow (spec §3,
§2.5-10). It intentionally does not name specific vendor endpoints/URLs
until an adapter for them is actually implemented and reviewed against
their terms of use -- listing an unverified endpoint here would violate the
"never fabricate a source" rule as much as fabricating data would.

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
| Market data (OHLCV, corporate actions) | `src/data_sources/market/base.py::MarketDataProvider` | §3.2 | >=2 adapters (fallback + cross-check) |
| Fundamentals (financial statements) | `src/data_sources/fundamentals/base.py::FundamentalsProvider` | §3.3 | prioritize XBRL/structured over PDF/OCR |
| Macro (BI-Rate, inflation, FX, global macro) | `src/data_sources/macro/base.py::MacroDataProvider` | §3.4 | one per publisher |
| Industry/sector-specific metrics | `src/data_sources/industry/base.py::IndustryDataProvider` | §3.5 | one per sector where disclosed |
| News | `src/data_sources/news/base.py::NewsProvider` | §3.6 | target >=5 distinct domains per company analysis, cap ~10 |

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
