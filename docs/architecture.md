# Architecture

Status: Tahap 1 (scaffold). This describes the target shape; most modules
below are currently empty placeholders -- see each module's `__init__.py`
docstring for which Tahap implements it.

## Data flow

```
external sources (§3)
  -> data_sources/* adapters (SourcedValue envelope, provenance attached)
  -> ingestion/* (Prefect flows, Tahap 6 for scheduling, jobs runnable standalone before that)
  -> validation/* (OHLC consistency, balance-sheet equation, staleness, dup detection)
  -> *_raw tables (append-only, as-returned-by-provider)
  -> preprocessing/* (corporate-action adjustment, currency/unit normalization, point-in-time joins)
  -> *_clean tables / financial_statement_items / sector_specific_metrics
  -> features/{technical,fundamental,sector,macro,sentiment}/* -> technical_features / fundamental_features
  -> ml/{datasets,training,inference}/* -> model_features -> predictions
  -> valuation/* -> valuation_results
  -> recommendation/* (combines fundamental/technical/valuation/macro/sentiment/model scores + guardrails, §21)
       -> recommendation_results
  -> rag/* (LLM narrative layer, reads structured JSON only, §12)
  -> apps/api (FastAPI, §26) -> apps/web (dashboard, §25)
```

Orchestration (Prefect, ADR 0002) schedules this chain per spec §23; every
stage is also independently runnable/testable outside the scheduler.

## Point-in-time discipline

`available_at` (not `period_end`, not "today") is the clock every stage
must respect. See ADR 0003. This is what makes backtests and historical
recommendations reproducible and leakage-free (spec §16).

## Provider abstraction

`src/data_sources/<category>/base.py` defines an abstract interface per
data category (market, fundamentals, macro, industry, news). Concrete
adapters (Tahap 2) implement these interfaces; business logic in
`ingestion/`, `features/`, etc. depends only on the interfaces, never on a
specific vendor -- see `src/data_sources/base.py` for the shared
`SourcedValue` provenance envelope every adapter method must return.

## Numeric computation vs. narrative (LLM boundary)

See ADR 0004. `features/`, `valuation/`, `ml/`, `recommendation/` are pure
deterministic Python with no LLM dependency. `rag/` is the only module
allowed to call an LLM, and only for summarization/classification/narrative
generation over data those other modules already computed.

## Storage

PostgreSQL + TimescaleDB (time-series) + pgvector (news embedding
similarity). See `docs/database_schema.md` for the table list and
`src/database/models/mixins.py` for the mandatory lineage columns.

## Deployment

Docker Compose (`docker-compose.yml`) runs the same containers locally and
on a server. Tahap 1 brings up `db` + `api` only; `web`, `scheduler`
(Prefect), `mlflow`, and `worker` are added as their respective phases
(§38 Tahap 4-6) produce something for them to run.
