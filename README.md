# IDX Investment Intelligence Platform

Automated research and decision-support platform for stocks listed on the
Indonesia Stock Exchange (IDX): market data, financial statements, macro,
sector metrics, and news are ingested and turned into technical +
fundamental + valuation + sentiment + ML-driven recommendations, shown on a
dashboard. See the full spec context in `docs/`.

**This is a research/decision-support tool, not a trading system and not a
guarantee of profit.** See `docs/risk_and_limitations.md`.

## Status: Tahap 2 in progress (market data)

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
- Provisional multi-source corporate actions (`docs/corporate_actions.md`)
  and cross-provider reconciliation (IDX itself is not reachable -- see
  `docs/data_sources.md`).
- CLI: `python -m src.cli ...` (providers check, market smoke-test/
  backfill/update/reconcile, corporate-actions sync).

**Not yet implemented**: fundamentals/macro/industry/news adapters,
feature engineering, models, valuation, recommendations, dashboard. See
`docs/architecture.md` and the phase plan (Tahap 3-7) in `docs/adr/`.

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

Not yet implemented -- these instructions are added as each phase ships
(Tahap 3: features; Tahap 4: models; Tahap 5: valuation + recommendations;
Tahap 6: API/dashboard/scheduler; Tahap 7: tests/docs/CI).

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
