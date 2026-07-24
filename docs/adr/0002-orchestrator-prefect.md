# ADR 0002: Orchestration via Prefect

## Status
Accepted (Tahap 1).

## Context
Spec §5 requires picking exactly one orchestration framework (Prefect or
Airflow) and using it consistently for the ingestion -> feature ->
inference -> valuation -> recommendation -> dashboard-refresh -> drift ->
retraining pipeline (§5, §23).

## Decision
Use **Prefect** (3.x).

Reasoning, in this project's context specifically:
- Primary local development happens on Windows without WSL by default;
  Airflow's local dev story assumes a Linux-like environment (Docker/WSL2
  is close to mandatory), while Prefect runs natively as a plain Python
  process.
- The project starts from zero orchestration infra -- Prefect's lower
  operational footprint (no dedicated metadata DB + webserver + scheduler
  + separate worker processes required just to run one flow locally) means
  Tahap 2 ingestion jobs can be flows from day one instead of first
  standing up an Airflow deployment.
- Flows are plain Python functions/tasks, which fits a codebase where
  pipeline steps are already being written as testable Python functions
  (spec §29 requires unit-testing pipeline logic) -- no separate DAG-file
  DSL to keep in sync.

## Consequences
- All scheduled work (spec §23 daily schedule) is defined under
  `src/orchestration/` as Prefect flows/deployments, added in Tahap 6.
- If operational needs later demand Airflow-specific features (e.g. complex
  cross-team DAG dependencies), migrating means rewriting flows -- accepted
  as a low-probability, addressable-later risk given the project's current
  single-team scope.
