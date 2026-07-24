# IDX Investment Intelligence Platform

Automated research and decision-support platform for stocks listed on the
Indonesia Stock Exchange (IDX): market data, financial statements, macro,
sector metrics, and news are ingested and turned into technical +
fundamental + valuation + sentiment + ML-driven recommendations, shown on a
dashboard. See the full spec context in `docs/`.

**This is a research/decision-support tool, not a trading system and not a
guarantee of profit.** See `docs/risk_and_limitations.md`.

## Status: Tahap 1 (project scaffold)

What exists right now:
- Full repository structure (`src/`, `apps/`, per `docs/architecture.md`).
- Database schema (29 tables) + Alembic migrations, with mandatory
  source-lineage columns on every fact table (`docs/database_schema.md`).
- Abstract provider interfaces for market/fundamentals/macro/industry/news
  data (`src/data_sources/*/base.py`) -- no concrete adapters yet.
- A minimal FastAPI app with a `/api/v1/health` endpoint.
- `docker-compose.yml` running `db` (Postgres + TimescaleDB + pgvector) and
  `api`.
- Architecture decision records (`docs/adr/`).

What does **not** exist yet: real data ingestion, feature engineering,
models, valuation, recommendations, or the dashboard. See `docs/architecture.md`
and the phase plan (Tahap 2-7) referenced throughout `docs/adr/`.

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

## Backfill / pipelines / training / dashboard

Not yet implemented -- these instructions are added as each phase ships
(Tahap 2: ingestion; Tahap 3: features; Tahap 4: models; Tahap 5: valuation
+ recommendations; Tahap 6: API/dashboard/scheduler; Tahap 7: tests/docs/CI).

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
