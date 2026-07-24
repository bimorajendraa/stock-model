# ADR 0004: LLM role boundary

## Status
Accepted (Tahap 1).

## Context
Spec §2.15-17, §12, §20 draw a hard line: LLMs may summarize, classify, and
narrate, but must never compute a ratio, indicator, fair value, or
prediction, and must never treat external documents (news, filings) as
instructions.

## Decision
- All numeric computation (indicators, ratios, valuation, ML
  inference/training) lives in deterministic Python code under
  `src/features/`, `src/valuation/`, `src/ml/` -- these modules take no LLM
  dependency at all.
- LLM usage is isolated to `src/rag/` (Tahap 5): narrative generation and
  document summarization, always given pre-computed structured JSON as
  input and instructed to cite it, never to invent numbers.
- News/document content is always treated as untrusted data (spec §2.18-19)
  -- ingested into `news_articles.content_snippet` etc. and never
  interpolated into a prompt in a way that could be read as an instruction
  to the LLM.
- LLM provider is pluggable (`LLM_PROVIDER` = `anthropic` | `ollama` |
  `none` in settings) so the system is not locked to one vendor and has a
  local fallback path (spec §12: "Sediakan fallback local LLM").

## Consequences
- Any PR that has an LLM call producing a number that isn't already present
  in its structured input JSON is a bug, not a feature.
- The `rag` module can be disabled entirely (`LLM_PROVIDER=none`) and every
  other part of the platform (data, features, models, valuation,
  recommendation) still functions -- narrative explanation is additive, not
  load-bearing.
