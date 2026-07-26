# News sentiment scoring (spec section 3.6)

Status: real deep-learning sentiment classifier wired into `news_sentiment`,
run for real against the currently ingested news. **A real production-data
contamination bug was found and fixed while building this** (see "A real
bug found live" below) -- documented in full rather than only reporting
the clean final numbers.

## Model choice: checked live, not assumed (2026-07-26)

The user asked for a deep-learning approach (LSTM or similar) rather than
an LLM -- consistent with spec section 2.15/2.12: sentiment must be a
reproducible, auditable model output, never narrated/guessed by an LLM.
A transformer (BERT) was used instead of an LSTM specifically because it
meant a real, already-trained, already-evaluated Indonesian model could be
used rather than training one from scratch with no labeled Indonesian
financial-sentiment dataset available.

Two real candidates were checked live before picking one, same "verify,
don't assume" discipline as every other data source in this project:

| Candidate | Domain | Real reported metric | Verdict |
|---|---|---|---|
| `michaelmanurung/finbert-indonesia` | Finance-specific (500 labeled Indonesian headlines) | **accuracy 0.299, F1 0.276** on its own eval | **Rejected** -- worse than the 0.333 random baseline for 3 balanced classes. Domain match alone doesn't make a model usable. |
| `ayameRushia/bert-base-indonesian-1.5G-sentiment-analysis-smsa` | General-domain (IndoNLU's SmSA benchmark -- Indonesian product/app reviews, **not finance-specific**) | 93.73% accuracy on SmSA | **Used** -- best real number found among the candidates checked. |

Labels: `Positive` / `Neutral` / `Negative` (the model's own 3 classes).
`src/features/sentiment/model.py` derives:
- a continuous **score** in `[-1, 1]` = `P(Positive) - P(Negative)`
- the DB's 5-point Indonesian label (`sangat_negatif|negatif|netral|positif|sangat_positif`)
  by splitting each polarity into a "sangat_" (very) variant at a
  confidence >= 0.75 -- **this threshold is this project's own disclosed
  heuristic**, not something the model reports; the model has no native
  5-class notion.

## Real, honest finding: the general-domain model under-reads terse financial headlines

Running for real against the actual ingested news (2026-07-26): **28 of
29 real (article, company) pairs scored `netral`**, including headlines a
domain expert would call clearly positive or negative:

| Headline | Real meaning | Model's label |
|---|---|---|
| "Laba Bank Mandiri (BMRI) Lompat 24,4% Jadi Rp30,4 T" | profit jumped 24.4% -- positive | `netral` |
| "Pabrik Baja Krakatau Steel Kebakaran, Produksi Terganggu" | factory fire, disrupted production -- negative | `netral` |
| "Laba Bank J Trust (BCIC) Anjlok 28,9%" | profit plunged 28.9% -- negative | `netral` |
| "Kualitas Aset Terjaga, Profitabilitas BMRI Sangat Sehat" | explicitly uses "sangat sehat" (very healthy) | `sangat_positif` (0.998) -- the one case it got right |

**Likely cause, stated plainly rather than guessed away**: SmSA (the
model's training data) is full first-person product/app reviews
("barangnya bagus banget", "aplikasi ini jelek") -- a very different
register from terse, third-person financial headlines that convey
sentiment through numbers and domain terms ("anjlok", "melesat",
"terpangkas") rather than explicit everyday sentiment words. The model
only fires confidently on the one headline that happens to use an
everyday-review-style phrase ("sangat sehat"). **This is a real,
disclosed limitation of using a general-domain sentiment model on
financial news, not a bug** -- the earlier finance-specific alternative
that might have handled this register was checked and rejected for being
worse than random (see above). A genuinely finance-tuned Indonesian
sentiment model, if one with real, reported, above-random metrics
becomes available, would be a direct improvement over this.

## A real bug found live: test suite wrote fake sentiment onto real production data

While building `src/tests/test_sentiment_pipeline.py`, one test
(`test_article_with_no_entity_link_gets_no_sentiment_row`) called
`compute_sentiment_for_unscored_pairs` **without** scoping it to the
fixture company. Since the pipeline's real, intended behavior is to
process every unscored (article, company) pair *in the whole database*
(that's exactly what the real CLI command needs it to do), this
unscoped test call did exactly that against the **shared real database**
this project uses for integration tests -- scoring every real,
already-entity-linked production article with the test's hardcoded
always-positive fake scorer, and committing the result under fake
`model_version` values (`fake-test-model-v1`, `a-different-model-v2`).

Caught by directly inspecting a real run's results (many different real
headlines showing the *exact same* score, `0.8700`, was the tell -- real
model inference on genuinely different text does not coincidentally
collapse to one identical float). Diagnosed by tracing `model_version`
values back to the test file, not by guessing. Fixed two ways:
1. The offending test now scopes to `company_ids=[fixture_company.id]`
   too (harmless here since the article under test has no entity link
   regardless, but it removes the unscoped whole-database processing).
2. All 58 contaminated rows (`model_version IN ('fake-test-model-v1',
   'a-different-model-v2')`) were deleted from the real database, and
   `news compute-sentiment` was re-run cleanly, producing the 29 real
   rows discussed above.

`compute_sentiment_for_unscored_pairs` also gained an optional
`company_ids` filter parameter as part of this fix -- useful generally
(matches the `--tickers` scoping convention used elsewhere in this
project's CLI), not just for test isolation.

## What gets scored, and what structurally doesn't

One `news_sentiment` row per (article, linked company) pair -- the
classifier scores the whole article's title+summary text, not
per-company/aspect-based sentiment, so every company mentioned in one
article currently gets the *same* score (a real, disclosed
simplification).

**Structural limitation inherited from the existing schema, not
introduced here**: `news_sentiment.company_id` is a non-nullable FK, so
an article with **no** ticker entity link gets **no** sentiment row at
all, even if it carries real market-wide sentiment. Given
`docs/news.md`'s entity-linking coverage is partial (ticker-code-only
matching), most ingested articles never get scored under the current
schema -- not worked around by inventing a NULL-company convention that
isn't there.

`news_sentiment` has no unique constraint on (article_id, company_id) --
by design (`news.py`'s model docstring: a re-scored article must never
silently overwrite an older score). Idempotency is therefore "skip pairs
already scored by this exact `model_version`" -- scoring the same
articles again with a *different* model_version adds new rows rather than
replacing anything.

## CLI

```
python -m src.cli news compute-sentiment                # score every unscored (article, company) pair
python -m src.cli news compute-sentiment --limit 50      # cap how many pairs get scored in one run
```

Not yet wired into the daily scheduled task (`docs/news.md`) -- run
manually for now.

## What's not built yet

- **Aspect-based / per-company sentiment** -- one score per article,
  replicated across every company it mentions.
- **A finance-tuned Indonesian model with real, above-random metrics** --
  the one candidate checked was rejected (see above); the general-domain
  model used instead visibly under-reads terse financial headlines (see
  above).
- **Sentiment feeding into the recommendation engine, beyond a guardrail
  flag** -- `src/recommendation/pipeline.py` now reads the company's most
  recent `news_sentiment` row and adds a `recent_negative_sentiment`
  guardrail when it's negative, but deliberately never lets it change the
  label or confidence -- see `docs/recommendation.md`'s "Sentiment: a
  guardrail flag only" section for why, given this doc's own finding that
  the model under-reads negative financial news as neutral.
- **Scoring articles with no entity link** -- structural schema
  limitation, see above.
