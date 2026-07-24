# ADR 0001: Core tech stack

## Status
Accepted (Tahap 1).

## Context
The platform needs a backend language capable of numeric computation
(indicators, ratios, valuation, ML), a relational store with strong
time-series and JSON support, and a deployment story that runs both locally
(Windows dev machine) and on a server via containers.

## Decision
- **Language**: Python 3.11+ for all backend/data/ML code (`src/`, `apps/api`).
- **API**: FastAPI + Pydantic (schema validation, OpenAPI docs for free).
- **Database**: PostgreSQL, with the TimescaleDB extension for OHLCV /
  macro / feature time-series and pgvector for news-embedding similarity
  search (dedup, RAG retrieval).
- **ORM/migrations**: SQLAlchemy 2.0 (typed declarative models) + Alembic.
- **Containerization**: Docker + Docker Compose for local and server
  deployment, so "runs locally" and "runs on a server" are the same
  artifact.
- **Frontend**: Next.js/React (per spec §25), deferred to Tahap 6 --
  nothing to render until the pipeline produces data.

## Consequences
- One language (Python) end-to-end for backend/data/ML lowers the barrier
  to reviewing numeric-correctness-critical code (indicators, ratios,
  valuation) -- spec §2.15-16 requires all of this be deterministic,
  non-LLM code, so keeping it in one typed, testable language matters more
  than polyglot performance wins.
- TimescaleDB + pgvector on top of vanilla Postgres avoids operating two
  separate database systems (a time-series DB and a vector DB) for a
  single-instance deployment.
