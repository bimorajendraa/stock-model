# IDX Investment Intelligence Platform

Automated research and decision-support platform for stocks listed on the
Indonesia Stock Exchange (IDX): market data, financial statements, macro,
sector metrics, and news are ingested and turned into technical +
fundamental + valuation + sentiment + ML-driven recommendations, shown on a
dashboard. See the full spec context in `docs/`.

**This is a research/decision-support tool, not a trading system and not a
guarantee of profit.** See `docs/risk_and_limitations.md`.

## Status: Tahap 6 in progress (API + dashboard); Tahap 1-5 substantially done

**Tahap 1 (scaffold)** -- done: full repo structure, 32-table schema +
Alembic migrations with mandatory source-lineage columns on every fact
table (`docs/database_schema.md`), provider interfaces, minimal FastAPI
app, `docker-compose.yml` (`db` + `api`), ADRs (`docs/adr/`).

**Tahap 2 (market data)** -- done and verified against real data:
- Emiten metadata sync: 947 real IDX companies (ticker + name only --
  see `docs/data_sources.md`'s company-master-data limitation).
- Multi-provider capability system (`docs/provider_capabilities.md`):
  Twelve Data (company reference, proven; OHLCV gated behind a live
  capability probe, not just "key present") with a Yahoo Finance
  research-only fallback, refused outright in production mode.
- Real OHLCV ingestion with validation + quarantine
  (`docs/market_data.md`): full universe backfilled -- 1,706,497 rows
  across 944 of 947 companies (2016-2026; the 3 that failed are confirmed
  non-equity codes in Twelve Data's own listing, not a bug), idempotency
  proven, two real bugs found and fixed via live smoke testing (32-bit
  volume overflow, Postgres parameter-count limit on large backfills).
- Preprocessing into `market_prices_clean` (`docs/market_data.md`):
  1,706,497 rows across 944 companies, 1:1 with raw, 226 bars flagged
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
  adjustment-scaled OHLC. Run for real against the top 50 companies by
  market cap: 4.28M feature rows written.
- Macro/industry-wide series (`docs/macro_data.md`): `YahooFinanceMacroAdapter`
  (USD/IDR FX, IHSG composite, US 10Y Treasury yield -- global proxy, NOT
  BI-Rate -- WTI crude) plus `BPSMacroAdapter`, added once the user
  registered and provided a real, free BPS Web API key -- real national
  monthly inflation, 126 points, 2016-2026. 2 real bugs found and fixed
  live (BPS's 3-year `th` request cap; an undocumented no-separator key
  encoding in its response) plus a real point-in-time bug found across
  *both* adapters (a decade of backfilled points was being stamped
  `available_at=now` instead of each point's own real availability date)
  -- 10,729 total points across 5 series. Real BI-Rate itself remains
  uncovered (Bank Indonesia's site is HTML-only, no API).
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
  sector peers, needing >=3 peers) -- 72 metric rows across the 4
  (sector, industry) groups with enough real peers.
- News ingestion (`docs/news.md`): 4 real RSS feeds (Antara News, CNBC
  Indonesia, Detik Finance, Katadata -- Kontan's feed is empty, Bisnis.com/
  IDX/Investor Daily are blocked or 404), upserted + ticker-entity-linked
  against the full real company universe. A real false-positive bug found
  live (`EMAS`/`NAIK` are real tickers that are also ordinary Indonesian
  words) fixed by requiring case-sensitive ticker matching. Real run: 232
  articles, 26 entity links. A Prefect flow wrapping the same logic exists
  (`src/orchestration/news_flow.py`) matching ADR-0002, plus a Windows
  Scheduled Task for daily 06:00 automation -- registered successfully but
  **not yet confirmed to fire reliably unattended** (diagnosed as an
  `Interactive`-logon-type issue that needs an elevated session to fix;
  see `docs/news.md`'s scheduling section for the exact command to run).
- Deferred: support/resistance ensemble, real per-company sector-specific
  disclosed metrics (NPL/NIM/CAR etc. -- still no real source), sentiment
  *scoring* (news is now ingested, but no sentiment signal is computed
  from it yet).

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
  sentiment, still unbuilt) remain untested. **No model here is used by
  anything -- there is no recommendation engine yet.**

**Fundamentals (Tahap 3.3 + 8 branches)** -- raw statement ingestion and
ratio computation both done (`docs/fundamentals.md`):
`YahooFinanceFundamentalsAdapter` (research_only, same status as the
OHLCV adapter), a 30-code provider-agnostic account taxonomy, 461
statements / 11,909 line items across 50/50 companies, sector differences
(banks vs. non-banks) correctly reflected as omitted line items rather
than fabricated zeros. 13 fundamental ratios (margins, ROE/ROA, DER,
current ratio, FCF/OCF margin, book value/share, point-in-time P/E and
P/B) computed deterministically -- 5,811 ratio rows / 50 companies, real
BBCA figures sanity-checked (ROE 20.4%, P/B 2.56x). Honest, documented
limitations: Yahoo doesn't expose real filing dates, so `available_at` is
a conservative estimate (period_end + 120/60 days), never claimed as a
real disclosure date; only one provider exists (no redundancy yet). A
follow-up audit of this step caught and fixed a real bug (a test was
destroying real BBCA production data via unscoped cleanup) -- see
`docs/fundamentals.md` for the full account.

**Valuation (Tahap 5)** -- one method done (`docs/valuation.md`):
**self-relative (own-history) multiple valuation** -- a company's latest
EPS/book-value-per-share x the 25th/50th/75th percentile of its OWN
historical P/E/P/B range, needing no external assumption (no discount
rate, no peer group). Chosen over DCF/peer-relative specifically because
those need data this project doesn't have yet -- a real discount-rate
proxy (no macro adapter) and real sector classification (no verified free
source) -- not fabricating either rather than guessing. Run for real on
the top-50 set: 50/50 companies, 42 using both P/E+P/B methods, 8 falling
back to P/B-only (loss-making companies where P/E is conventionally
undefined), spot-checked against real prices (e.g. BBCA's fair value sits
close to its current price; TLKM/ASII show larger gaps). Honestly
documented limitation: this measures "cheap/expensive vs. its own past,"
not intrinsic value, and that past is both short (~4 years) and partly
circular (built from past market prices).

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
numbers above.

**Sentiment scoring (spec section 3.6, `docs/sentiment.md`)** -- a real
pretrained Indonesian BERT classifier (deep learning, never an LLM, per
spec section 2.15/2.12), chosen after a finance-specific alternative was
checked live and rejected for scoring below the random baseline on its
own eval. Honest finding: the general-domain model under-reads terse
financial headlines, defaulting to neutral on clearly positive/negative
real news (28 of 29 real scored pairs). A real test-pollution bug was
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
requests. Real coverage stated plainly: only 50 of 947 companies have
fundamentals/valuation/recommendation computed, so most tickers return
real company/sector info with empty snapshot sections, not fabricated
values.

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

**CI** -- GitHub Actions (`.github/workflows/ci.yml`): lint, unit tests,
and integration tests against the real `docker-compose` db service +
Alembic migrations (mirrors local dev rather than reinventing Postgres
setup in CI YAML). Real-external-network `*_live.py` tests are excluded
from CI by design (BPS/RSS/HuggingFace calls belong in local/manual
verification, not a gate that goes red for reasons unrelated to a real
regression).

**Not yet implemented**: real BI-Rate (BPS inflation now covered, BI's
own site remains HTML-only), real per-company sector-specific disclosed
metrics (NPL/NIM/CAR etc.), a confirmed-reliable unattended daily news
schedule (task registered with a Docker/privilege workaround, still not
independently confirmed to fire unattended -- `docs/news.md`),
company-name-alias entity linking, full-universe sector/fundamental/
valuation/recommendation coverage (only the top-50-by-market-cap set so
far), models beyond the Tahap 4 baselines (no proven edge yet),
sector-relative valuation, DCF, investment_style classification, a
validated ML signal in the recommendation engine, dashboard auth/charts,
Prefect orchestration beyond the one news flow. See `docs/architecture.md`
and the phase plan (Tahap 3-7) in `docs/adr/`.

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
pytest -v -m integration  # requires: docker compose up -d db first
```

Tests marked `integration` are excluded by default (`addopts` in
`pyproject.toml`) and must be selected explicitly -- they hit a real
Postgres instead of mocks, to prove things like upsert/lineage/FK behavior
actually work against the live schema, not just that the ORM calls compile.

## Market data ingestion (Tahap 2)

```bash
python -m src.cli providers check              # which provider would be used, and why
python -m src.cli market smoke-test --count 10 # real ingestion for N real tickers from the DB
python -m src.cli market backfill --count 50   # full-history backfill
python -m src.cli market backfill --ticker BBCA
python -m src.cli market update                # incremental update for all companies
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
```

See `docs/technical_features.md`, `docs/fundamentals.md`,
`docs/sector_classification.md`,
`docs/macro_data.md`, `docs/valuation.md`, `docs/recommendation.md`, and
`docs/news.md`.
Model training (Tahap 4 baselines) is script-driven, not yet a CLI
command -- see `docs/model_methodology.md`. Dashboard (Tahap 6) not yet
implemented.

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
