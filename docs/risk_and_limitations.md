# Risk and limitations

This platform is a research and decision-support tool. It is **not**:
- A guarantee of profit.
- A system that executes trades.
- A substitute for independent due diligence or professional financial
  advice.

## Data limitations (free/public sources)

- End-of-day data is the default mode; nothing is presented as real-time
  unless a licensed, real-time-permitting provider is configured (spec
  §2.10, §3.2).
- Free/public sources can lag, restate, or gap -- every number carries its
  `source`, `retrieved_at`, `available_at`, and `quality_status` so staleness
  and provenance are always visible, never hidden (spec §2.11, §33).
- News coverage may fall short of the 5-10 domain target for less-covered
  issuers; the platform reports the actual count and flags `cakupan berita
  terbatas` rather than padding it (spec §3.6).
- Newly-listed (IPO) companies are flagged as having limited history (spec
  §2.13) -- ratios, technical indicators, and model outputs relying on
  multi-year windows will be marked `data tidak mencukupi` until enough
  history accumulates.

## Model limitations

- All predictions carry uncertainty (confidence intervals / quantiles) and
  a model version; none are point guarantees, especially at the 3-5 year
  horizon (spec §14).
- Models are evaluated against baselines (buy-and-hold, IHSG, simple
  fundamental score) and must clear quality gates (spec §32) before being
  promoted to serve recommendations -- a model that doesn't beat its
  baseline stays a challenger, not a champion.
- Backtests include transaction costs, slippage, and liquidity limits
  where feasible; they do not assume unlimited market impact-free size
  (spec §19).

## Recommendation guardrails

The recommendation engine will not output `LAYAK DIBELI` under conditions
including (non-exhaustive, see spec §21): stale critical data, low model
confidence, incomplete financials, material going-concern issues, unresolved
suspensions, or unconfirmed material news. When guardrails can't be cleared,
or data is simply insufficient, the output is `DATA TIDAK MENCUKUPI`, not a
downgraded-but-still-numeric recommendation.

## What this platform will never claim

Per spec §35: no "pasti naik", "dijamin untung", "wajib beli", guaranteed
price targets, or similar absolute claims. Narrative output (LLM-generated,
see ADR 0004) is constrained to describe what the structured data shows,
with sources cited.
