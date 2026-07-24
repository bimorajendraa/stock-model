# ADR 0003: Mandatory source lineage + point-in-time discipline

## Status
Accepted (Tahap 1).

## Context
Spec §2.11-13, §3.3, §16 require that (a) every stored number traces back
to a named source, retrieval time, availability time, and validation
status, and (b) no model, feature, or backtest ever uses information before
it was actually public (no leakage from restated financials, future news,
or undisclosed corporate actions).

## Decision
- Every fact table inherits `SourceLineageMixin`
  (`src/database/models/mixins.py`): `source_id`, `retrieved_at`,
  `available_at`, `period_start`, `period_end`, `currency`, `unit`,
  `is_restated`, `quality_status`, `raw_payload_hash`/`raw_payload`.
- Every provider adapter method returns a `SourcedValue` envelope
  (`src/data_sources/base.py`), never a bare value -- so it is structurally
  impossible to write a fact-table row without lineage, since the ingestion
  layer only ever receives `SourcedValue` objects to unpack.
- Feature tables (`fundamental_features`) key off `as_of_date`, explicitly
  documented as the statement's `available_at`, never its `period_end`.
- `data_source_registry` is a first-class table (not a config file) so
  `source_id` foreign keys are enforced by the database, not convention.

## Consequences
- Every future migration that adds a fact table must include these
  columns; a code-review checklist item / test should catch a table that
  doesn't.
- Downstream feature/training code must always filter on `available_at <=
  as_of_date`, never `period_end <= as_of_date` -- this is the leakage test
  surface referenced in spec §16 and will be covered by automated leakage
  tests in Tahap 3-4.
