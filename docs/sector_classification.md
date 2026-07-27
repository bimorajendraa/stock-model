# Sector classification and sector-relative metrics (spec section 3.1/3.5)

Status: real sector/industry classification implemented and verified
(`src/ingestion/sector_classification.py`), plus one sector-relative
fundamental metric implemented on top of it
(`src/features/sector/{relative,pipeline}.py`). Fixes a gap flagged
repeatedly across this project's docs: `companies.sector_registry_id` had
been NULL for every company since Tahap 1 because no adapter populated
it -- market-data adapters only ever returned ticker+name
(`docs/data_sources.md`'s company-master-data limitation).

## What was actually investigated (2026-07-25)

Checked live: `yfinance`'s `Ticker.get_info()` (already trusted,
research_only, for OHLCV/fundamentals/market cap) returns real GICS-style
`sector`/`industry` fields for IDX tickers. Verified across companies
spanning banks, telcos, conglomerates, miners, tech, and consumer
goods -- e.g. BBCA.JK -> sector="Financial Services", industry="Banks -
Regional"; GOTO.JK -> sector="Technology", industry="Software -
Infrastructure"; ANTM.JK -> sector="Basic Materials", industry="Gold".
Real, diverse, plausible classification, not a single fallback bucket.

## Two real bugs found and fixed -- both real DB constraints, only found by running against every company

1. **`sector_registry.sector_code` has a global `UNIQUE` constraint**
   (not composite with `subsector_code`). An early version of this
   module keyed rows on (sector_name, industry_name) but stored only
   `slug(sector_name)` as `sector_code` -- so the second industry within
   the same broad sector (e.g. "Financial Services" -> "Insurance -
   Property & Casualty" arriving after "Banks - Regional" already
   existed) hit a real `psycopg.errors.UniqueViolation` mid-run.
2. **`sector_code` is also `VARCHAR(32)`.** The first fix (concatenating
   sector+industry slugs) produced codes like
   `financial_services_insurance_property_casualty` (49 chars), which
   then hit a real `psycopg.errors.StringDataRightTruncation`.

Fixed by deriving `sector_code` from a short, deterministic hash of the
full (sector, industry) pair (`_sector_code()`) -- guaranteed unique and
guaranteed to fit 32 chars, at the cost of not being human-readable on
its own. `sector_name`/`subsector_name` (`VARCHAR(128)`, plenty of room)
are what any human-facing display should read from instead.

A third, smaller issue: the first real run crashed partway through an
*alphabetically-ordered* default slice (not the intended top-50-by-
market-cap set) before these fixes landed, leaving a couple of stragglers
(AALI, ABBA) pointing at now-orphaned pre-fix rows. Found by querying for
`SectorRegistry` rows with zero companies still referencing them,
reclassified the 2 affected companies with the fixed code, then deleted
the 4 confirmed-orphaned stale rows -- verified zero companies referenced
them first, not deleted blind.

## `SectorRegistry.metrics_config_key`/`valuation_config_key`

Both required (non-nullable) columns intended for a future config-driven
per-sector metrics/valuation system (spec section 3.5/section 10) that
doesn't exist yet -- populated with the sector's own code as a stable
placeholder key, not a fabricated distinct workflow. Documented here so
it isn't mistaken for a real config system already existing.

## Sector-relative fundamental metrics (`src/features/sector/`)

**Not the same as** `IndustryDataProvider.get_metrics` (spec section
3.5) -- that interface is for metrics only obtainable from real
sector-specific disclosures (banking NPL/NIM/CAR, mining stripping
ratio, etc.), which no adapter in this project provides, and still
doesn't. This is instead a **cross-sectional percentile rank** of a
company's own already-computed fundamental ratio
(`financial_ratios` -- `net_margin`, `roe`, `debt_to_equity`) against its
real sector peers -- only meaningful now that sector classification is
real (comparing a bank's ROE to its real bank peers, not an arbitrary or
fabricated grouping).

- Needs >= 3 real peers with an applicable value for that specific ratio
  (`MIN_PEERS`) -- fewer would make a percentile look falsely precise;
  not computable, never fabricated.
- A company missing one ratio (e.g. a bank with no applicable
  `debt_to_equity` in this project's taxonomy) still gets ranked on the
  ratios it does have -- one missing metric doesn't block the others,
  and doesn't block other companies' rankings either (verified by
  `test_compute_sector_relative_metrics_missing_ratio_does_not_block_others`).
- Written to `sector_specific_metrics` (`SectorSpecificMetric`, Tahap 1
  schema) as `{ratio_name}_percentile_in_sector`, 0-100 scale.

## Real run results (2026-07-25)

`python -m src.cli sector classify --tickers <top-50-by-market-cap>`:

- **50/50 companies classified**, 0 skipped.
- **26 real `SectorRegistry` rows** created across the set -- e.g. Basic
  Materials (13 companies across Gold/Coal/Metals-Mining/Chemicals
  industries), Financial Services (9, mostly Banks - Regional), Consumer
  Defensive (7), Communication Services (6), Energy (6, all Thermal
  Coal), Real Estate (4), Industrials/Technology/Utilities (2 each),
  Healthcare (1).

`python -m src.cli sector compute-relative-metrics`:

- **72 metric rows written** across the 4 (sector, industry) groups with
  >= 3 companies: Financial Services/Banks - Regional (7 companies, 21
  metrics), Basic Materials/Other Industrial Metals & Mining (6, 18),
  Energy/Thermal Coal (6, 18), Communication Services/Telecom Services
  (5, 15). Every other (sector, industry) combination in the top-50 set
  has fewer than 3 real peers and correctly produced 0 metrics -- not a
  bug, just an honest reflection of how concentrated this particular
  50-company slice is within a handful of industries.

## CLI

```
python -m src.cli sector classify --tickers BBCA,TLKM,ASII
python -m src.cli sector classify --offset 0 --limit 150
python -m src.cli sector compute-relative-metrics   # DB-only, no network -- run after classify
python -m src.cli sector compute-disclosed-metrics --tickers BBCA,ADRO
```

## Remaining gaps

- **Official disclosed-metric coverage** -- banking NPL/NIM/CAR/LDR/CASA and
  mining reserve/production/cost computations are implemented, but require
  applicable facts from the authorized XBRL archive. Missing facts produce no
  metric, not an estimate. Telco ARPU/churn remains unimplemented.
- **Sector-relative valuation** is now implemented with at least three usable
  same-sector peers; see `docs/valuation.md`. Production valuations have not
  yet been recomputed with this method.
- **Full-universe classification** currently covers 917/942 equities; 25
  provider records returned no usable classification.
- **investment_style classification** in the recommendation engine
  (`docs/recommendation.md`) -- real sector data could inform this now,
  not wired up yet.
