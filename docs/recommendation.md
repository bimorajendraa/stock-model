# Recommendation engine (Tahap 5, spec section 21)

Status: one deterministic engine implemented and verified against real
data (`src/recommendation/scoring.py`, `src/recommendation/pipeline.py`),
writing into the `recommendation_results` table from the Tahap 1 schema.

## The most important design decision: no ML signal is used

Tahap 4's baseline models were tested three independent ways -- adding
fundamental features, longer label horizons, a different market-cap tier
(`docs/model_methodology.md`) -- and none showed a validated edge; some
actively overfit. This engine **does not use any ML prediction at all**.
Feeding an unproven, near-random signal into a recommendation would
manufacture false confidence -- the opposite of spec section 18's "never
claim a model is free of overfitting, report the evidence." The honest
response to "the model doesn't work yet" is to leave it out, not
down-weight it a little and call the job done. This is recorded
explicitly in every result (`scores.ml_signal_used = False`), not a
silent omission someone could mistake for an oversight.

The engine is built entirely from two things that ARE real, computed,
and defensible:

1. **Valuation position** (`valuation_results`, `docs/valuation.md`) --
   is the current price below/within/above the company's own
   bear-to-bull fair-value range.
2. **Fundamental quality** (`financial_ratios`, `docs/fundamentals.md`)
   -- latest net margin, ROE, and debt-to-equity.

Both are today's-state facts computed deterministically from real data,
not predictions of the future.

## Scoring logic

`src/recommendation/scoring.py`:

- **Valuation position**: `undervalued` (price < bear fair value),
  `overvalued` (price > bull fair value), or `fair` (in between). `None`
  (not computable) if any input is missing -- never defaults to "fair."
- **Fundamental quality**: `weak` if net margin or ROE is <= 0;
  `healthy` if ROE >= 10% AND (debt-to-equity is not_applicable, e.g. a
  bank, OR debt-to-equity < 1.0x); `mixed` otherwise. `None` if net
  margin or ROE is missing (debt-to-equity alone missing does NOT block
  classification -- not_applicable is not the same as missing-and-fatal).
  **Every threshold here (10% ROE, 1.0x D/E) is a simple, commonly-cited
  equity-analysis rule of thumb, not a statistically validated cutoff** --
  documented plainly so it can be revisited, not presented as more
  rigorous than it is.
- **Combination**: weak fundamentals -> `HINDARI` regardless of
  valuation (a cheap stock with weak fundamentals is a value trap, not a
  bargain). Otherwise driven by valuation position: undervalued ->
  `LAYAK_DIBELI` (healthy) or `AKUMULASI_BERTAHAP` (mixed); overvalued ->
  `TUNGGU_HARGA`; fair -> `HOLD`. Either input missing ->
  `DATA_TIDAK_MENCUKUPI`, never a guessed label.
- **Confidence**: a simple 0-1 completeness heuristic (average of the
  valuation's own `data_quality_score` and how many of the 3 fundamental
  inputs were available) -- not a statistical confidence interval, same
  honesty convention as `ValuationResult.data_quality_score`.

## Sentiment: a guardrail flag only, never a label/confidence input

`docs/sentiment.md`'s `news_sentiment` is now read (the company's most
recent scored article, by the article's own `published_at`) -- but,
**deliberately, the same discipline as excluding the ML signal**: it
never changes the label or confidence. It only adds
`"recent_negative_sentiment"` to `guardrails_triggered` when that latest
reading is `negatif`/`sangat_negatif`. Why not weight it into the score
directly: `docs/sentiment.md` documents that the sentiment model has a
real, measured bias toward `netral` on terse financial headlines (28 of
29 real pairs) -- so a negative reading here is likely meaningful (the
model rarely misreads clearly positive news as negative), but its
*absence* must never be read as "no negative news exists" -- most real
negative financial news gets missed as `netral`, not caught as a
false-negative. Treating a rarely-firing, one-directionally-reliable
signal as more than an extra flag would repeat exactly the mistake this
engine already avoids with the ML signal. `scores.sentiment_signal_used`
records whether this company had *any* scored news at all (`false` for
most companies today -- see `docs/sentiment.md`'s coverage numbers).

## What's recorded per result

- `scores` (JSONB): every component value that went into the decision --
  valuation position, fundamental quality, current price, bear/base/bull
  fair values, net margin, ROE, debt-to-equity, the explicit
  `ml_signal_used: false` marker, and `sentiment_label`/`sentiment_score`/
  `sentiment_signal_used` (see above; `null`/`false` when this company has
  no scored news yet).
- `guardrails_triggered`: e.g. `high_leverage` (debt-to-equity > 2.0x),
  `valuation_not_computable`, `fundamental_quality_not_computable`,
  `recent_negative_sentiment` (see above).
- `entry_zone`: for `LAYAK_DIBELI`/`AKUMULASI_BERTAHAP`, the
  conservative-to-base fair value range; for `TUNGGU_HARGA`, the
  conservative-to-bear range (the price zone worth waiting for).
- `suggested_horizon`: a fixed `"6-12 bulan"` string -- the implicit
  mean-reversion assumption behind the self-relative valuation method,
  **not** derived from data, stated as an assumption.
- `investment_style`: left `NULL` -- not classified in this first cut,
  rather than fabricating a "value"/"growth" label without a real basis.

## Real run results (2026-07-26, re-run after wiring in the sentiment guardrail)

`python -m src.cli recommendation compute --tickers <the same real 50 companies with valuation_results>`:

- **50/50 companies succeeded**, 0 skipped, **0 `DATA_TIDAK_MENCUKUPI`**
  -- fundamentals coverage for this set is solid enough that every
  company had both a valuation and a classifiable fundamental profile.
- Label distribution: **25 HOLD, 13 TUNGGU_HARGA, 7 AKUMULASI_BERTAHAP,
  4 HINDARI, 1 LAYAK_DIBELI** -- a real, varied distribution (not
  uniform/fabricated-looking), unchanged from the pre-sentiment run since
  sentiment never drives the label (see above).
- Confidence ranged 0.625-0.969 (median 0.969) -- most companies have
  full data; a few (e.g. CDIA, a recent IPO) score lower from shorter
  fundamentals history, consistent with `docs/fundamentals.md`'s finding
  that recent IPOs have less real history, not a bug.
- **7 companies triggered `high_leverage`**; **0 triggered
  `recent_negative_sentiment`** -- honest, not a sign the wiring is
  broken: only 6 of these 50 companies (AMMN, BMRI, CPIN, GOTO, PTRO,
  SUPR) had any scored news at all, and every one of those latest
  readings happened to be `netral` (`docs/sentiment.md`'s real run
  produced only 1 non-neutral result out of 29 total, and it wasn't for
  any of these 6). The guardrail is verified working by a dedicated test
  with an injected negative reading
  (`test_compute_recommendation_negative_sentiment_triggers_guardrail_but_not_label`),
  not asserted only by absence of a real trigger in production data.
- Spot-checked for consistency with `docs/valuation.md`'s own numbers:
  TLKM/ASII (priced well above their own historical fair-value range) ->
  `TUNGGU_HARGA`; GOTO (priced below its own historical range) ->
  `AKUMULASI_BERTAHAP`; UNVR is the sole `LAYAK_DIBELI` -- a real,
  plausible story (Unilever Indonesia's share price has been under
  sustained pressure while core profitability metrics stayed healthy),
  not an arbitrary pick.

## Idempotency

Same day-scoped pattern as `valuation_results`
(`docs/valuation.md`'s idempotency section): re-running today replaces
today's row only, past snapshots stay untouched. Verified by
`test_compute_recommendation_is_idempotent_per_day_not_across_days`.

## CLI

```
python -m src.cli recommendation compute --tickers BBCA,TLKM,ASII
python -m src.cli recommendation compute --offset 0 --limit 150
```

## What's not built yet

- **investment_style classification** -- left `NULL`, no real
  methodology decided yet.
- **Guardrails beyond `high_leverage`** -- spec section 21 likely expects
  a richer guardrail set (e.g. going-concern flags, data staleness) --
  this project's `going_concern_flag`/`auditor_opinion` are always
  `None`/`False` since Yahoo Finance doesn't expose them
  (`docs/fundamentals.md`), so those specific guardrails aren't
  computable from current data either.
- **Incorporating a validated ML signal** -- deliberately deferred, not
  omitted by oversight; would need a baseline that actually clears the
  bar `docs/model_methodology.md` describes, which none currently do.
- **Sentiment is now incorporated, but only as a guardrail flag** (see
  above) -- not weighted into `confidence`, not a positive-sentiment
  guardrail (only negative triggers one), and macro signals still aren't
  incorporated at all.
- **A dashboard surfacing this** -- `docs/api.md`'s
  `/companies/{ticker}/snapshot` now serves it over HTTP; the actual
  `apps/web` UI is still not started.
