# IDX Investment Intelligence Platform

Automated research and decision-support platform for stocks listed on the
Indonesia Stock Exchange (IDX): market data, financial statements, macro,
sector metrics, and news are ingested and turned into technical +
fundamental + valuation + sentiment + ML-driven recommendations, shown on a
dashboard. See the full spec context in `docs/`.

**This is a research/decision-support tool, not a trading system and not a
guarantee of profit.** See `docs/risk_and_limitations.md`.

## Status: Tahap 6 MVP done; full-universe coverage and operations in progress

**Tahap 1 (scaffold)** -- done: full repo structure, 32-table schema +
Alembic migrations with mandatory source-lineage columns on every fact
table (`docs/database_schema.md`), provider interfaces, minimal FastAPI
app, `docker-compose.yml` (`db` + `api`), ADRs (`docs/adr/`).

**Tahap 2 (market data)** -- done and verified against real data:
- Instrument metadata sync: 947 real IDX records (942 equities + 5 indices;
  ticker, name, and `asset_type` -- see `docs/data_sources.md`'s
  company-master-data limitation).
- Multi-provider capability system (`docs/provider_capabilities.md`):
  Twelve Data (company reference, proven; OHLCV gated behind a live
  capability probe, not just "key present") with a Yahoo Finance
  research-only fallback, refused outright in production mode.
- Real OHLCV ingestion with validation + quarantine
  (`docs/market_data.md`): full equity universe backfilled -- 1,706,497 rows
  across all 942 equities plus 2 indices (2016-2026; 3 other indices have
  no Yahoo Finance series), idempotency
  proven, two real bugs found and fixed via live smoke testing (32-bit
  volume overflow, Postgres parameter-count limit on large backfills).
- Preprocessing into `market_prices_clean` (`docs/market_data.md`):
  1,706,497 rows across the same 944 instruments, 1:1 with raw, 226 bars flagged
  (not deleted) as outliers.
- Market cap ranking (`docs/market_data.md`): shares_outstanding for 926
  companies via Yahoo Finance `fast_info`, real top-50-by-market-cap
  (BBCA/BREN/DCII/BBRI/BMRI...) -- caught and fixed a real bug that
  silently dropped mega-caps whose latest bar had a null close.
- Provisional multi-source corporate actions (`docs/corporate_actions.md`)
  and cross-provider reconciliation (IDX itself is not reachable -- see
  `docs/data_sources.md`).
- CLI: `python -m src.cli ...` (providers check, market smoke-test/
  backfill/update/reconcile/fetch-marketcap/top-marketcap,
  corporate-actions sync).

**Tahap 3 (technical + macro/industry features)** -- started
(`docs/technical_features.md`, `docs/macro_data.md`):
- 45 technical indicators (trend/momentum/volatility/volume +
  market-relative) implemented from scratch in pandas, computed on
  adjustment-scaled OHLC. Full available-price universe now covered:
  71.2M feature rows across all 942 equities plus 2 indices.
- Macro/industry-wide series (`docs/macro_data.md`): 11 real series / 11,042
  points covering BI-Rate, BI lending/deposit facilities, JISDOR, BPS
  inflation, GDP/unemployment, USD/IDR, IHSG, US 10Y, and WTI. The official
  Bank Indonesia HTML/XLS adapters handle sources that have no JSON API;
  every series retains point-in-time availability metadata.
- Market-relative technical features (`beta_60/252`, `alpha_60/252` --
  a simplified excess-return proxy, explicitly NOT CAPM alpha,
  `relative_strength_5/20/60/120/252`) vs. IHSG -- unblocked once IHSG
  data existed, run for real on the same top-50 set. Testing this against
  a live DB caught (and fixed) two real bugs, both in synthetic test
  fixtures' calendar assumptions, not the pipeline itself -- verified by
  checking against real BBCA data first (`docs/technical_features.md` has
  the full account).
- Real sector/industry classification (`docs/sector_classification.md`):
  `yfinance` gives real GICS-style sector/industry for IDX tickers,
  fixing a gap flagged since Tahap 2 (`companies.sector_registry_id` had
  been NULL for every company). 2 real DB-constraint bugs found and
  fixed live (a global unique constraint collision across industries in
  the same broad sector; a 32-char column overflow). 50/50 companies
  classified into 26 real sectors, plus a sector-relative fundamental
  metric (percentile rank of ROE/net margin/debt-to-equity within real
  sector peers, needing >=3 peers). The completed traversal classified
  917/942 equities (25 returned no sector data) and wrote 1,771 metric
  rows across 597 companies.
- News ingestion (`docs/news.md`): 5 RSS feeds in research mode (Antara,
  CNBC Indonesia, Detik Finance, Katadata, and CNA Indonesia); production
  mode excludes CNA because its RSS terms are personal/non-commercial.
  Entity linking now covers provider tickers, current tickers, legal company
  names, previous tickers, and imported previous names, with match method and
  matched text stored for audit. A Docker-supervised daily scheduler uses a
  PostgreSQL advisory lock and DB-backed health check. Unit/health checks pass;
  a full 24-hour unattended observation has not yet been completed.
- Sector-specific disclosed metrics are implemented for banks (NPL, NIM,
  CAR, LDR, CASA) and mining companies (reserves, production, reserve life,
  cash cost, stripping ratio). They remain empty until the corresponding
  facts are present in authorized official filings; values are never guessed.
  Support/resistance ensemble remains deferred.

**Tahap 4 (model training)** -- baselines only (`docs/model_methodology.md`):
- Point-in-time labeling, date-based train/validation/test split with
  embargo + purging (never random -- spec forbids it for time-series).
- Naive/rule/logistic-regression/random-forest/small-MLP baselines, run
  for real on the top-50 dataset. Honest finding: none robustly beat the
  naive baseline on held-out test data, and random forest/MLP show clear
  overfitting (train AUC 0.65-0.69 vs. test AUC 0.52-0.53) despite
  regularization -- consistent with technical-only features being close
  to their practical ceiling.
- Re-run with the fundamental ratios (below) attached as extra features,
  point-in-time-joined: **another honest negative result**, not a win --
  the dataset shrinks ~76% (fundamentals only cover back to ~2022),
  random forest's overfitting got strictly worse (train AUC 0.84, test
  AUC *dropped* to 0.51), and the small test-AUC upticks for logistic
  regression/MLP are within noise on a 1,205-row test set, not evidence
  fundamentals help.
- Follow-up: tried longer label horizons (60/120/252 days, not just 20)
  to see if fundamentals just needed a timescale closer to how ratios
  like ROE actually matter. Technical+fundamental **couldn't even be
  evaluated** at 120/252 days -- the ~4-year fundamentals window is too
  short once embargo/validation/test splits are subtracted, splits come
  up empty (a real data-depth blocker, not a feature-completeness one).
  Technical-only alone: h=120 logistic regression hit the best test AUC
  seen yet (0.559, small train/test gap) but that's 1 cell out of 40
  tried across two sessions -- flagged as "watch, don't trust" per spec
  section 18's multiple-comparisons caution, not a discovered edge. h=252
  was *worse than random* across every model (0.39-0.46 test AUC) --
  plausible regime shift or autocorrelation-collapsed effective sample
  size, reported plainly either way.
- Follow-up 2: tested whether the ceiling is a top-50-mega-cap-specific
  efficiency artifact -- reran technical-only on a genuinely different
  tier, ranks 201-250 by market cap (~Rp4-6T, 8-19x smaller than top-50's
  cutoff), real technical features computed for real (3.36M rows, 50/50
  companies). Result: **no small-cap edge** -- h=20 results are
  indistinguishable from mega-cap (within 0.01 AUC on every model), and
  the h=120 "best result so far" (0.559) **failed to replicate**
  out-of-sample on mid-caps (0.485, actually below random) -- direct
  evidence it was noise from testing many combinations, not a real edge.
  Three independent angles (more features, longer horizons, different
  market-cap tier) now all point the same way: no robust edge found yet
  from technical/fundamental-only signals on this exchange, which is
  meaningfully stronger evidence for a structural ceiling than any one
  result alone -- though genuinely new information types (macro, news/
  sentiment) remain untested as ML feature branches. **No model here is
  used by the recommendation engine**; the deterministic engine described
  below deliberately excludes the unvalidated ML outputs.

**Fundamentals (Tahap 3.3 + 8 branches)** -- raw statement ingestion and
ratio computation both done (`docs/fundamentals.md`):
`IDXOfficialXBRLArchiveAdapter` for authorized/manual official IDX XBRL
downloads plus publication manifests, with a priority-chain fallback to
`YahooFinanceFundamentalsAdapter` (research_only), and a provider-agnostic
core + industry account taxonomy. The initial
 top-50 run produced 461 statements / 11,909 line items; the completed traversal
now covers 650/942 equities with 6,060 statements / 154,168 line items. Sector differences
(banks vs. non-banks) correctly reflected as omitted line items rather
than fabricated zeros. 13 fundamental ratios (margins, ROE/ROA, DER,
current ratio, FCF/OCF margin, book value/share, point-in-time P/E and
 P/B) computed deterministically -- now 74,451 ratio rows / 650 companies, real
BBCA figures sanity-checked (ROE 20.4%, P/B 2.56x). Honest, documented
limitations: official manifest rows use the real, timezone-aware exchange
publication timestamp, while Yahoo fallback rows still use a conservative
estimate (period_end + 120/60 days), explicitly identified by
`available_at_basis`. The current database has not been re-ingested from an
official archive because no authorized XBRL manifest/files are configured;
its historical rows therefore retain the estimated-date caveat. A
follow-up audit of this step caught and fixed a real bug (a test was
destroying real BBCA production data via unscoped cleanup) -- see
`docs/fundamentals.md` for the full account.

**Valuation (Tahap 5)** -- three method families implemented
(`docs/valuation.md`): own-history P/E/P/B, same-sector peer-relative P/E/P/B
(minimum three usable peers), and explicit-assumption free-cash-flow DCF with
bear/base/bull plus a 3x3 sensitivity grid. Every database input is filtered
point-in-time by `available_at <= as_of_date`. DCF stays disabled unless all
three rate assumptions are configured, so the application never invents a
discount or growth rate. The historical method was run for real on
the top-50 set: 50/50 companies, 42 using both P/E+P/B methods, 8 falling
back to P/B-only (loss-making companies where P/E is conventionally
undefined), spot-checked against real prices (e.g. BBCA's fair value sits
close to its current price; TLKM/ASII show larger gaps). Honestly
documented limitation: this measures "cheap/expensive vs. its own past,"
not intrinsic value, and that past is both short (~4 years) and partly
circular (built from past market prices). The completed traversal has valid
valuations for 619 companies; 31 additional ratio-covered companies lacked
the minimum historical multiple depth. Peer/DCF code is covered by unit and
PostgreSQL integration tests but has not yet been rolled out across those
production rows; DCF also awaits operator-supplied assumptions.

**Recommendation engine (Tahap 5, spec section 21)** -- one deterministic
engine done (`docs/recommendation.md`), combining valuation position +
fundamental quality (net margin, ROE, debt-to-equity) into a labeled
call (`LAYAK_DIBELI` | `AKUMULASI_BERTAHAP` | `TUNGGU_HARGA` | `HOLD` |
`HINDARI` | `DATA_TIDAK_MENCUKUPI`). **Deliberately uses no ML
prediction at all** -- Tahap 4's models never showed a validated edge
across three independent tests, and feeding an unproven signal into a
recommendation would manufacture false confidence; this is recorded
explicitly per result (`scores.ml_signal_used = false`), not a silent
omission. Weak fundamentals always -> `HINDARI` regardless of price (a
cheap stock with weak fundamentals is a value trap, not a bargain). Run
for real on the top-50 set: 50/50 companies, 0 `DATA_TIDAK_MENCUKUPI`,
a real varied distribution (25 HOLD, 13 TUNGGU_HARGA, 7
AKUMULASI_BERTAHAP, 4 HINDARI, 1 LAYAK_DIBELI), 7 companies flagged
`high_leverage`, results spot-checked for consistency with the valuation
numbers above. Current coverage is 619 companies; the latest-label distribution
is 266 `HOLD`, 170 `TUNGGU_HARGA`, 142 `HINDARI`, 37
`AKUMULASI_BERTAHAP`, and 4 `LAYAK_DIBELI`.

**Sentiment scoring (spec section 3.6, `docs/sentiment.md`)** -- an
Indonesian BERT classifier plus a transparent high-precision financial
phrase calibration layer and company-specific sentence extraction. The
rules cover explicit profit changes, default/insolvency, fraud, suspension,
and dividends; event category, severity, and horizon are stored separately.
This fixes known neutral-bias examples deterministically, but is not claimed
as a generally validated finance model: an independent labeled Indonesian
financial-news benchmark is still needed. A real test-pollution bug was
found and fixed live (an unscoped integration test call wrote fake
sentiment onto real production articles -- caught because many different
real headlines showed an identical score, impossible from real inference
on different text) and the contaminated rows were deleted.

**Recommendation + sentiment (`docs/recommendation.md`)** -- sentiment
is now read into the recommendation engine, but strictly as a
`recent_negative_sentiment` guardrail *flag*, never a label/confidence
input -- the same "don't manufacture false confidence from an
unreliable signal" discipline already applied to excluding the ML
model, justified by the sentiment model's own documented neutral-bias
finding above.

**API (spec section 26, `docs/api.md`)** -- a read-only FastAPI surface
over everything above: company list/detail, a per-ticker snapshot
(latest technical/fundamental/sector-relative values + valuation +
recommendation in one call), per-company news+sentiment, and a
recommendation screener. Verified against the real database via
`TestClient` and a real running `uvicorn` process hit with real HTTP
requests. Real equity coverage stated plainly: 650 of 942 equities have
fundamentals/ratios and 619 have valuation/recommendation. The remaining
tickers return real company/sector info with empty snapshot sections, not
fabricated values. Company lists default to equities; `asset_type=all`
exposes all 947 master records.

**Dashboard (spec section 25, `docs/dashboard.md`)** -- a real Next.js
16 (App Router) dashboard consuming the API above: company list+search,
a per-company page (recommendation/valuation/technical/fundamental/
sector-relative/news+sentiment), and the recommendation screener.
Verified end-to-end with both the API and dashboard actually running,
hit with real HTTP requests against real data (not a mockup). A real bug
was found and fixed live: a stale Docker `api` container from hours
earlier was silently answering requests on the same port ahead of the
freshly-started dev server, traced via `Get-NetTCPConnection` showing
three processes bound to port 8000.

**CI** -- GitHub Actions (`.github/workflows/ci.yml`): Python lint/unit
tests, deterministic integration tests against the real `docker-compose`
PostgreSQL service + Alembic migrations, and frontend lint/build on Node
22. Tests marked `live` plus `*_live.py` files are excluded by design
(Yahoo/BPS/RSS/HuggingFace calls belong in local/manual verification, not
a gate that goes red for an external outage or rate limit).

**Remaining operational/data gaps**: obtain and configure an authorized IDX
XBRL archive (there are no official-filing rows in the current database),
populate a verified company-alias CSV (the table currently has zero rows),
observe the Docker news scheduler for at least one real unattended daily
cycle, and independently benchmark the finance-calibrated sentiment model.
Fallback coverage is still incomplete (currently sector/fundamental/
historical-valuation coverage is 917/650/619 of 942 equities). Also deferred:
models beyond the Tahap 4 baselines (no proven edge), investment-style
classification, a validated ML signal in recommendations, dashboard auth/
charts, and broader Prefect orchestration. See `docs/architecture.md` and
the phase plan (Tahap 3-7) in `docs/adr/`.

## Prerequisites

- Python 3.11+
- Docker + Docker Compose
- (Windows without WSL is fully supported for the Python/API side; the
  `Makefile` targets assume a Unix-style venv layout (`.venv/bin/...`) --
  on native Windows, run the underlying commands directly with
  `.venv\Scripts\...` instead, or use WSL/Git Bash.)

## Setup

```bash
python -m venv .venv
# Windows (PowerShell): .venv\Scripts\Activate.ps1
# Unix / Git Bash:      source .venv/Scripts/activate  (or .venv/bin/activate on Linux/macOS)
pip install -e ".[dev]"

cp .env.example .env
# edit .env if you need non-default DB credentials or provider keys
```

## Running the database

```bash
docker compose up -d db
```

This starts PostgreSQL with the TimescaleDB and pgvector extensions
enabled (via `docker/db/init/001_extensions.sql`).

## Migrations

```bash
alembic upgrade head          # apply all migrations
alembic revision --autogenerate -m "description"   # after changing models
```

## Running the API

Locally:
```bash
uvicorn apps.api.main:app --reload
```
Or via Docker Compose:
```bash
docker compose up -d api
curl http://localhost:8000/api/v1/health
```

## Tests

```bash
pytest -v                 # default: unit tests only, no database needed
pytest -v -m "integration and not live" --ignore-glob="**/*_live.py"
                           # requires: docker compose up -d db first
```

Tests marked `integration` are excluded by default (`addopts` in
`pyproject.toml`) and must be selected explicitly -- they hit a real
Postgres instead of mocks, to prove things like upsert/lineage/FK behavior
actually work against the live schema, not just that the ORM calls compile.
Files named `*_live.py` additionally call external providers and stay out
of the deterministic suite/CI via the explicit ignore glob above.

## Market data ingestion (Tahap 2)

```bash
python -m src.cli providers check              # which provider would be used, and why
python -m src.cli market smoke-test --count 10 # real ingestion for N real tickers from the DB
python -m src.cli market backfill --count 50   # full-history backfill
python -m src.cli market backfill --ticker BBCA
python -m src.cli market update                # incremental update for all equities
python -m src.cli market reconcile --count 5   # cross-provider price cross-check
python -m src.cli corporate-actions sync --ticker BBCA
```

See `docs/market_data.md`, `docs/provider_capabilities.md`, and
`docs/corporate_actions.md` for what each command actually does, what it
depends on (`TWELVE_DATA_API_KEY` for company sync; a real Twelve Data key
or `MARKET_DATA_PROVIDER=yahoo_finance`/research mode for OHLCV), and known
limitations.

## Pipelines / feature engineering / training / dashboard (Tahap 3+)

```bash
python -m src.cli features compute-technical --tickers BBCA,TLKM,ASII
python -m src.cli fundamentals sync --tickers BBCA,TLKM,ASII
python -m src.cli features compute-fundamental-ratios --tickers BBCA,TLKM,ASII
python -m src.cli macro sync
python -m src.cli sector classify --tickers BBCA,TLKM,ASII
python -m src.cli sector compute-relative-metrics
python -m src.cli valuation compute --tickers BBCA,TLKM,ASII
python -m src.cli recommendation compute --tickers BBCA,TLKM,ASII
python -m src.cli news sync

# Full-universe/resumable batch examples
python -m src.cli fundamentals sync --all --only-missing
python -m src.cli sector classify --all --only-missing
python -m src.cli features compute-fundamental-ratios --all --only-eligible --only-missing
python -m src.cli valuation compute --all --only-eligible --only-missing
python -m src.cli recommendation compute --all --only-eligible --only-missing
```

Resumable batches persist one attempt row per pipeline/emiten in
`pipeline_company_results`. `--only-missing` skips both companies that
already have output and attempts whose retry window is still active:
`no_data` is retried after 7 days and `failed` after 1 hour. Use
`--retry-deferred` with `--only-missing` for an operator-forced retry;
an explicit `--tickers` list always bypasses the cooldown. A scheduled
resume with nothing due is a successful no-op (exit code 0), not a failed
pipeline run. Default batch selection is restricted to active equities;
an explicit ticker remains an operator override for another asset type.

See `docs/technical_features.md`, `docs/fundamentals.md`,
`docs/sector_classification.md`,
`docs/macro_data.md`, `docs/valuation.md`, `docs/recommendation.md`, and
`docs/news.md`.
Model training (Tahap 4 baselines) is script-driven, not yet a CLI
command -- see `docs/model_methodology.md`. The Next.js dashboard lives
in `apps/web`; see `docs/dashboard.md`.

## Limitations of free/public data sources

See `docs/risk_and_limitations.md` -- end-of-day (not real-time) data by
default, possible news-coverage gaps below the 5-domain target, and
limited history for newly-listed companies are all surfaced in the data
itself (`quality_status`, `data tidak mencukupi`), never silently patched
over.

## Disclaimer

This platform does not execute trades and does not guarantee investment
outcomes. All recommendations carry a confidence level, risk factors, data
sources, and last-updated timestamp -- treat them as one input to your own
research, not as financial advice.
