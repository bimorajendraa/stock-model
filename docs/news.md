# News ingestion, entity linking, and daily operation

Status: five Indonesian business/news RSS feeds are supported in research
mode; four are allowed in production mode. Articles are idempotently stored,
linked to companies with auditable match metadata, and can be synchronized by
a Docker-supervised daily scheduler.

## Feed coverage and usage policy

| Feed | Tier | Research | Production |
|---|---:|---:|---:|
| Antara Ekonomi | 2 | yes | yes |
| CNBC Indonesia Market | 2 | yes | yes |
| Detik Finance | 3 | yes | yes |
| Katadata | 3 | yes | yes |
| CNA Indonesia Business | 2 | yes | no |

CNA's official RSS page limits free use to personal/non-commercial use, so the
feed is tagged `personal_noncommercial_research_only` and is filtered out when
`NEWS_USAGE_MODE=production`. This adds media diversity without silently
granting production rights. Kontan's observed feed was empty; Bisnis.com/IDX
blocked automated access; an Investor Daily endpoint was not verified. Those
sources are not bypassed or guessed.

```dotenv
NEWS_USAGE_MODE=research
```

RSS is a recent-item window, not a searchable archive. Coverage therefore
remains dependent on what each publisher exposes, and no claim of complete
market coverage is made.

## Entity linking

`src/ingestion/entity_matching.py` matches title, summary, and content snippet
against:

1. provider-supplied tickers;
2. current ticker codes (case-sensitive);
3. current legal company names after stripping common legal suffixes;
4. previous tickers from `company_aliases`;
5. previous company names from `company_aliases`.

Short or generic one-word name variants are rejected to reduce false
positives. Case-sensitive ticker matching is intentional: real IDX tickers
such as `EMAS` and `NAIK` are also ordinary Indonesian words. Every
`news_entities` row records `match_method`, `matched_text`, and relevance
score, so a link can be reviewed instead of being an opaque boolean.

The alias table is currently empty in the existing production database. It can
now be populated from a verified CSV without editing code:

```csv
ticker,previous_ticker,previous_name,effective_from,effective_to,reason
NEWC,OLDC,PT Nama Lama Tbk,2010-01-01,2020-12-31,official issuer history
```

```bash
python -m src.cli companies import-aliases --file data/company_aliases.csv
```

The importer validates company tickers and ISO dates and is idempotent. The
CSV's provenance still matters; unverified aliases should not be imported.

## Manual sync and sentiment

```bash
python -m src.cli news sync --lookback-days 3
python -m src.cli news compute-sentiment
```

Article identity is the canonical URL, so repeated syncs update rather than
duplicate it. Provider failures are recorded per run and do not fabricate
empty articles. Sentiment details are in `docs/sentiment.md`.

## Durable daily scheduler

`news-scheduler` in `docker-compose.yml` runs once on container startup and
then at the configured Jakarta-local time. It is supervised by Docker's
`restart: unless-stopped`, uses a PostgreSQL advisory lock to prevent duplicate
replicas, and writes actual `news_sync` runs to `pipeline_runs`.

```dotenv
APP_TIMEZONE=Asia/Jakarta
NEWS_SCHEDULE_HOUR=6
NEWS_SCHEDULE_MINUTE=0
```

Useful checks:

```bash
docker compose up -d db news-scheduler
docker compose logs news-scheduler
docker compose exec news-scheduler python -m src.orchestration.news_scheduler --healthcheck
```

The health check fails for a stale running job, a failed latest job, or no
completed sync in 36 hours. Scheduler timing, advisory locking, Compose
configuration, and the DB health check are tested. A full real 24-hour
unattended observation has not yet been completed, so operational reliability
is implemented and instrumented but not yet claimed as proven in production.

The Prefect wrapper remains available for broader orchestration, but the daily
service does not require an ephemeral Prefect server to stay alive.

## Remaining quality work

- Observe at least one real unattended cycle and alert delivery under an
  actual host restart/network failure.
- Import a verified alias/name-history dataset; only the ingestion path exists
  today.
- Add licensed or explicitly production-safe publishers to exceed four domains
  in production mode.
- Measure entity-link precision/recall on a labeled article sample.
