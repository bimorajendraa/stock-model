# Data source capability/health registry ("Section B")

Status: real, working audit registry -- 18 real sources cataloged, probed
live against their actual endpoints (2026-07-26), not configuration that
was written but never run.

## Why a second registry, not a change to the existing one

`DataSourceRegistry` (`data_source_registry`) already existed (Tahap 1)
and is what every fact table's `SourceLineageMixin.source_id` foreign-keys
to -- referenced across ~10 ingestion/feature modules and ~15 test files.
Audited before writing anything (per this task's own rule 1: audit before
changing) and deliberately **not** touched or repurposed: it's a
lightweight "which adapter wrote this row" pointer, with no room for a
source that's only a *candidate* (checked live, no adapter built yet) or
a health status that can change independently of any ingestion run.

`DataSourceCapability` (`data_sources`, this doc) is additive: a real
capability/health-audit layer, linked to `DataSourceRegistry` only
loosely (matching `source_code` against `DataSourceRegistry.name` where
an adapter already exists), never a hard FK -- so a source can be audited
before any adapter/ingestion code exists for it at all.

## Schema

`src/database/models/ops.py::DataSourceCapability`, migration
`77eab1ada604`. Enums exactly as specified: `SourceType` (api/html/xlsx/
csv/zip/xbrl/xml/rss/pdf/document_repository), `AuthorityLevel`
(regulator/exchange/issuer/government/international_institution/
news_agency/business_media/general_media/aggregator/unofficial_provider),
`SourceUsageMode` (production_allowed/research_only/metadata_only/
verification_only/license_review), `SourceHealthStatus` (healthy/
degraded/blocked/empty/format_changed/rate_limited/
authentication_required/unverified).

## What "audit" actually means here

`src/data_sources/registry.py::probe_source` makes a real HTTP request
per source and classifies the result -- **HTTP 200 with a near-empty body
is never treated as success** (`_MIN_BODY_BYTES = 200`; a real page/feed/
API payload is never this small), and sources with a `content_marker`
must actually contain it (`FORMAT_CHANGED` if not -- distinguishes "page
structure changed" from "page unreachable," a real, different failure
mode). A source requiring an API key that isn't configured reports
`unverified` with a clear reason, not a false `blocked`.

## Real bugs found building this (not hypothetical)

- **`bps_webapi` and `imf_sdmx` both 404'd on their bare `base_url`** --
  neither is a valid endpoint by itself. Fixed with real, verified
  endpoints: BPS's own subject-catalog call
  (`/list/model/subject/domain/0000/key/{api_key}`, the same one the
  working `bps.py` adapter already uses) and IMF's real structure/
  dataflow catalog (`/structure/dataflow/IMF.STA`, checked live with curl
  before hardcoding it -- returns a real `dataflows` JSON array).
- **A stray `fake_fundamentals` row was found in the *existing*
  `data_source_registry`** while auditing what was already there --
  test-fixture contamination (matches the earlier real
  `news_sentiment` contamination bug from this project's history), zero
  real `financial_statement_items`/`financial_ratios` referenced it,
  deleted.
- **A real, previously undiscovered data-loss finding**: `docs/macro_data.md`
  and `README.md` claimed BPS's `id_inflation_mom` series had "126 real
  points, verified" -- but the actual `pipeline_runs` row for the one real
  `macro_sync` run shows `records_in=10603`, which is *exactly* the sum of
  the 4 Yahoo series alone (2749+2653+2547+2654), with zero room for BPS's
  126. The BPS points are not in `macro_series` today. Not silently
  re-asserted as still true -- flagged here, and re-verified for real as
  part of the macro-source expansion work (see `docs/macro_data.md`'s
  update for the corrected, re-run result).

## Real audit results (2026-07-26)

`python -m src.cli sources audit` (18 sources):

| source_code | category | health_status |
|---|---|---|
| yahoo_finance_market/fundamentals/macro | market/fundamentals/macro | healthy |
| twelve_data | market | authentication_required (demo key, expected) |
| bps_webapi | macro | healthy (after real-endpoint fix above) |
| bi_rate_html | macro | healthy |
| bi_jisdor | macro | healthy |
| bi_seki | macro | healthy |
| bi_sdds | macro | healthy |
| bi_indonia | macro | healthy |
| world_bank_indicators | macro | healthy |
| imf_sdmx | macro | healthy (after real-endpoint fix above) |
| fred | macro | unverified (no FRED_API_KEY configured -- degrades gracefully, not treated as blocked) |
| antara/cnbc/detik/katadata RSS | news | healthy |
| huggingface_sentiment_model | news | healthy |

**"healthy" here means "reachable, real non-trivial content returned" --
not "a parser exists for it yet."** The 5 `bi_*` entries being healthy is
exactly what unblocked building real adapters for them (see
`docs/macro_data.md`); `world_bank_indicators`/`imf_sdmx` being healthy is
what unblocked the international macro fallback adapters.

## CLI

```
python -m src.cli sources audit                    # probe every registered source
python -m src.cli sources audit --category macro    # probe only one data_category
python -m src.cli sources report                    # print the last recorded result for every source
```

## What's not built yet

- Only 18 sources cataloged so far -- covers what's already implemented
  plus this session's macro-expansion targets. Sections C/F/H/etc.'s
  candidate sources (IDX XBRL, OJK datasets, GDELT, etc.) get added to
  the catalog when those sections are actually built, not pre-seeded as
  guesses now.
- No scheduled/automatic re-audit -- run manually today.
