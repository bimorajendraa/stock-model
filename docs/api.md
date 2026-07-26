# API (spec section 26)

Status: read-only API surface built on top of every pipeline in
`docs/technical_features.md`, `docs/fundamentals.md`, `docs/valuation.md`,
`docs/recommendation.md`, `docs/sector_classification.md`,
`docs/sentiment.md`. **This layer computes nothing** -- every field
returned is exactly what those pipelines already wrote to the DB; there is
no business logic in `apps/api/`.

## Endpoints

```
GET /api/v1/health
GET /api/v1/companies?q=&offset=&limit=
GET /api/v1/companies/{ticker}
GET /api/v1/companies/{ticker}/snapshot
GET /api/v1/companies/{ticker}/news?offset=&limit=
GET /api/v1/recommendations?label=&offset=&limit=
```

- `companies` list/detail: `q` filters by ticker or company-name substring
  (case-insensitive). Detail includes the company's real sector/subsector
  from `sector_registry` (`docs/sector_classification.md`), `null` if the
  company hasn't been classified yet.
- `snapshot`: the single "give me everything computed for this ticker"
  endpoint a dashboard company page needs in one call -- **latest value
  per name** for `technical_features`, `financial_ratios` (only
  `is_applicable=true` rows), `sector_specific_metrics`, plus the most
  recent `valuation_results` and `recommendation_results` row. Any section
  is an empty list / `null` if that pipeline hasn't run for this company
  yet -- never a fabricated placeholder.
- `news`: this company's entity-linked articles (`docs/news.md`), newest
  first, each with its `docs/sentiment.md` sentiment if scored yet
  (`null` otherwise -- see that doc's note on why most articles never get
  a sentiment row: `company_id` there is non-nullable, so only
  entity-linked articles can ever have one).
- `recommendations`: screener across every company with a computed
  recommendation -- one row per company (latest `as_of_date` only, via a
  `GROUP BY company_id, MAX(as_of_date)` join, not just the newest row
  globally), sorted by confidence descending, optionally filtered by
  `label`.

## Real coverage, stated plainly

Every pipeline behind this API was run against the **top 50 companies by
market cap** (`docs/market_data.md`), not the full 947-company universe
(fundamentals/valuation/recommendation especially -- macro/technical
cover more). Querying the API for a ticker outside that set returns real
company info from `companies`/`sector_registry` but empty/`null` for
`technical`, `fundamental_ratios`, `valuation`, `recommendation`. The
`/recommendations` screener genuinely only has 50 companies to return
today; real label distribution (`GET /api/v1/recommendations`, checked
live 2026-07-26): `HOLD` 25, `TUNGGU_HARGA` 13, `AKUMULASI_BERTAHAP` 7,
`HINDARI` 4, `LAYAK_DIBELI` 1 -- not uniform, and not fabricated to look
more decisive than the underlying data supports (`docs/recommendation.md`
already documents that the recommendation engine deliberately excludes
the unproven Tahap 4 ML signal).

## Real end-to-end verification (2026-07-26)

Tested against the real database, both via `TestClient` (see
`src/tests/test_api_companies.py`, `test_api_recommendations.py` --
disposable fixture company/sector, same pattern as every other
integration test in this project) and by actually running
`uvicorn apps.api.main:app` and issuing real HTTP requests:
`GET /companies?limit=2` -> 947 real companies; `GET /companies/TLKM` ->
real sector `Communication Services` / `Telecom Services`;
`GET /companies/TLKM/snapshot` -> real technical feature values (e.g.
`sma_200=2957.28`); `GET /companies/BCIC/news` -> the real CNBC Indonesia
article about BCIC's H1-2026 profit decline with its real (if
under-reading, see `docs/sentiment.md`) `netral` sentiment label attached.

## What's not built yet

- **Write endpoints** -- spec section 26 describes this as a
  decision-support read surface; no `POST`/write endpoints exist and none
  are planned without a specific need.
- **Auth** -- no authentication/authorization layer. Fine for local/dev
  use, a real gap before any non-local deployment.
- **`apps/web` dashboard** -- this API exists to serve one; the frontend
  itself is still just `apps/web/README.md`, not started.
- **Sub-ticker filters on `/recommendations`** (e.g. by sector) -- only
  `label` filtering exists today.
