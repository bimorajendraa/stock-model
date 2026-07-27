# Financial-news sentiment

Status: company-linked articles are scored with an Indonesian BERT classifier
plus a transparent, high-precision finance calibration layer. Scores remain
model-versioned and never overwrite article text.

## Model and output

The base model is
`ayameRushia/bert-base-indonesian-1.5G-sentiment-analysis-smsa`. It is a
deep-learning classifier, not an LLM. The persisted version is
`smsa-ayamerushia-bert-id-1.5g+finance-rules-v1`.

For each `(article, company)` entity pair, the pipeline preferentially extracts
sentences that mention the matched ticker/name/alias. If no company-specific
sentence can be isolated, it falls back to the available article text. The
base probabilities produce a continuous score in `[-1, 1]` and the five labels
`sangat_negatif|negatif|netral|positif|sangat_positif`.

## Finance calibration and events

The general-domain model previously classified 28 of 29 real financial
headline/company pairs as neutral, including explicit profit increases and
declines. `src/features/sentiment/finance_rules.py` now adds narrow rules for
phrases whose financial polarity is explicit, including:

- profit/revenue growth or decline;
- default/insolvency and debt-payment failure;
- fraud/corruption investigations;
- trading suspension;
- dividend announcements.

Negation guards prevent phrases such as `tidak gagal bayar` from triggering a
default event. The rules can correct neutral base output only when an explicit
pattern matches; they are not a broad bag-of-words replacement for the model.
Detected `event_category`, `severity`, and `horizon` are stored with the
sentiment row.

## Idempotency and auditability

One score is written per article/company/model-version combination. Re-running
the same version skips existing pairs; a new model version creates new rows so
historical scores remain comparable. `company_id` is non-nullable, so articles
without an entity link are intentionally not scored as company sentiment.

```bash
python -m src.cli news compute-sentiment
python -m src.cli news compute-sentiment --limit 50
```

## What is and is not proven

Unit tests cover known positive/negative finance phrases, event metadata,
negation, and company-specific context extraction. This demonstrates expected
logic, not general accuracy. The combined model has not been measured on an
independent labeled Indonesian financial-news benchmark, so it must not be
described as validated or used as a direct recommendation/confidence input.

The recommendation engine therefore uses recent negative sentiment only as an
auditable guardrail flag. It cannot change the label or reported confidence.
Future work is to build or license a representative labeled benchmark, report
precision/recall by event and polarity, tune thresholds only on training data,
and retain a final untouched test set.
