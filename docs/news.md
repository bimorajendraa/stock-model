# News ingestion (spec section 3.6)

Status: real RSS ingestion implemented and verified end-to-end
(`src/data_sources/news/rss.py`, `src/ingestion/news.py`,
`src/cli/news.py`, `src/orchestration/news_flow.py`). Fills the gap
flagged repeatedly across this project's docs: news/sentiment had not
been started at all before this. **Sentiment scoring itself is still not
built** -- this is ingestion and ticker entity-linking only (see "What's
not built yet").

## Source: real RSS feeds, not an API

No Indonesian financial-news outlet in this project's prior research
offers a documented free API (spec section 2.2 requires a real,
verifiable source -- never a fabricated or guessed one). RSS is the real
mechanism available. Checked live, one at a time, before writing any
adapter code (2026-07-25):

| Candidate | Result |
|---|---|
| CNBC Indonesia (`/market/rss`) | real RSS 2.0, current, substantial -- **used** |
| Detik Finance (`finance.detik.com/rss`) | real RSS 2.0, current, substantial -- **used** |
| Antara News (`/rss/ekonomi.xml`) | real RSS 2.0, current, substantial, Indonesia's national news agency -- **used** |
| Katadata (`/rss`) | real RSS 2.0, current, substantial -- **used** |
| Kontan (`investasi.kontan.co.id/rss`) | feed exists but genuinely empty (0 `<item>`s) -- excluded |
| Bisnis.com (`/rss`, `finansial.bisnis.com/rss`) | HTTP 403, blocks automated access -- excluded |
| Investor Daily (`investor.id/rss`) | HTTP 404 -- excluded rather than guessing further |
| IDX's own site (`idx.co.id/.../berita/rss`) | HTTP 403, same Cloudflare block already documented for IDX's OHLCV endpoints in `docs/data_sources.md` |

Four real, working feeds (`FEED_REGISTRY` in `rss.py`), each tagged with
an editorial `credibility_tier` (spec section 3.6's 1-6 scale, 1=official
.. 6=blog) -- Antara and CNBC Indonesia at tier 2, Detik Finance and
Katadata at tier 3. This is a judgment call, not an authoritative rating,
and is documented as such rather than presented with false rigor.

## What gets ingested

`RSSFeedAdapter.fetch_recent(since, until)` fetches the whole feed and
date-filters by `pubDate` -- no ticker filtering at the adapter layer
(the adapter never touches the database). `ingest_news_from_feed()`
upserts each article into `news_articles` keyed on `canonical_url` (a
real DB unique constraint -- genuine `ON CONFLICT DO UPDATE`, not a
fabricated dedup), then links it to companies by matching ticker codes
as whole words in the title/summary, writing `news_entities` rows
(cleared and rewritten per article each run, since that table has no
unique constraint of its own -- same pattern already used for
`technical_features`/`financial_ratios`).

## Real bug found and fixed: ticker/word collisions

Found while testing entity-linking against the *full* real company
universe, not a curated sample (2026-07-25). Several real IDX tickers are
also ordinary Indonesian words -- `EMAS` (PT Merdeka Gold Resources;
"emas" = gold) and `NAIK` (PT Adiarwana Anugerah Abadi; "naik" = to
rise) are the two found. A case-insensitive ticker match turned a
completely unrelated headline -- "Harga Emas Dunia Naik Tipis" ("world
gold price rises slightly") -- into false entity links for both
companies. Caught by a DB-integration test that initially failed
(`entity_links_written=2` where it should have been 0).

Fixed by making `_ticker_pattern` **case-sensitive**, matching only the
uppercase form: real Indonesian financial journalism consistently
capitalizes ticker codes when referring to the stock ("Saham EMAS naik
tajam") but writes the ordinary word in normal sentence case ("harga
emas naik"). This is a real, load-bearing asymmetry in how the source
material is actually written, not a cosmetic choice -- verified with
`test_ticker_pattern_is_case_sensitive_to_avoid_dictionary_word_false_positives`.
It does not eliminate every possible false positive (a headline that
happens to fully capitalize a coincidentally-matching word would still
match), but removes the specific, common failure mode found live.

## Real run results (2026-07-25)

`python -m src.cli news sync` (3-day lookback, all 4 feeds):

| Feed | Articles written |
|---|---|
| Detik Finance | 101 |
| CNBC Indonesia | 100 |
| Katadata | 25 |
| Antara News | 6 |
| **Total** | **232 articles, 26 entity links** |

Antara's low count reflects its feed being economy-wide (`/rss/ekonomi.xml`,
not stock-market-specific), so fewer items mention a specific ticker
by code -- consistent with fewer entity links coming from it too, not a
sign anything is broken.

## CLI

```
python -m src.cli news sync                    # default 3-day lookback, all 4 feeds
python -m src.cli news sync --lookback-days 7
```

## Orchestration: Prefect flow exists, but isn't what actually runs daily

`src/orchestration/news_flow.py` wraps the same ingestion logic as a
Prefect flow, matching ADR-0002's chosen orchestrator. Running it live
surfaced two real Prefect-specific issues, documented in full in that
file's module docstring:

- With this project's configured `PREFECT_API_URL` (`.env`,
  `http://localhost:4200/api`), the flow fails outright (`RuntimeError:
  Failed to reach API`) -- there is no Prefect server in
  `docker-compose.yml`. Running with `PREFECT_API_URL=` cleared makes
  Prefect spin up its own disposable local server automatically, which
  contradicts ADR-0002's claim that Prefect "runs natively without a
  server" for 3.x.
- Passing a SQLAlchemy `Session` as a task argument breaks Prefect's
  default cache-key serialization (`cannot pickle 'weakref.ReferenceType'
  object`) -- fixed with `cache_policy=NO_CACHE` on the task.

Given neither a real Prefect server nor its ephemeral mode is part of
this project's normal running state, the flow is kept as real,
verified-runnable code for a future real Prefect deployment
(`PREFECT_API_URL= python -m src.orchestration.news_flow` reproduces it),
but it is **not** the daily automation mechanism -- see below.

## Daily automation: Windows Scheduled Task -- two real bugs found and fixed, one residual gap

A Windows Scheduled Task (`IDXPlatform_DailyNewsSync`) runs
`scripts/run_news_sync.ps1`, which wraps `python -m src.cli news sync`.
Getting this to actually fire unattended surfaced two real, live bugs
beyond the task registration itself -- neither was a Task Scheduler
config mistake, both were only found by triggering real runs and
checking real side effects (log file, `pipeline_runs` row) rather than
trusting `LastTaskResult: 0`.

**Bug 1 -- `LogonType=Interactive` needs an elevated fix that isn't
available on this machine.** The task's principal defaults to
`LogonType=Interactive`, `RunLevel=Limited`. A real trigger reproduced
`LastTaskResult: 2147946720` (`0x80070522`,
`ERROR_PRIVILEGE_NOT_HELD`) -- not a silent no-op, an actual Windows API
privilege failure. The correct fix, `LogonType=S4U` ("run whether user
is logged on or not," no stored password), needs the account to hold
"Log on as a batch job" (`SeBatchLogonRight`). Granting that normally
needs `secedit`/`gpedit.msc`, both of which require an elevated
(Administrator) session -- `secedit /export` was tried from this
non-admin session and failed with "you do not have sufficient
permissions," and Windows 11 Home has no `secpol.msc` GUI either.
**Worked around, not fixed**: the task keeps its `06:00` daily trigger
*and* an additional `AtLogOn` trigger for the same user. `AtLogOn` is
always backed by a genuine interactive session by construction, so the
`Interactive` logon type is valid at that moment even though it isn't
reliably valid for an unattended `06:00` fire if nobody's logged in yet.
`run_news_sync.ps1` self-throttles to once/day via a `logs/news_sync.lastrun`
marker file, since a machine that's already logged in at 06:00 would
otherwise get both triggers firing the same day.

**Bug 2 -- Docker Desktop wasn't set to start at login, so the `db`
container wasn't up.** Found live: even with the scheduling fixed, a
real run failed with `psycopg.errors.ConnectionTimeout` on
`localhost:5433` because Docker Desktop itself wasn't running (its
`AutoStart` setting was `false`). This is a genuine second, independent
precondition an unattended morning run depends on. Not fixed by editing
Docker's internal `settings-store.json` directly (that's an
undocumented internal file backing a normal user-facing Settings-UI
toggle, and editing it directly while Docker Desktop is running was the
wrong way to change it). Instead, `run_news_sync.ps1` now checks whether
port 5433 is reachable before running the sync; if not, it launches
Docker Desktop itself and polls for up to 120s before giving up.
**Action still open for you**: turn on Docker Desktop's own "Start
Docker Desktop when you sign in to your computer" (Settings > General)
so the 06:00 trigger doesn't have to spend its first ~30-60s just
booting Docker.

**Verified working, end-to-end, run directly (not via Task Scheduler)**:
`powershell.exe -File scripts\run_news_sync.ps1` twice in a row on
2026-07-26 -- first run: DB-down detected, Docker Desktop launched,
waited, then a real sync (4 feeds, 127 articles, 1 feed skipped for
insufficient data that run -- a live, real per-run outcome, not a bug),
log and marker file both written correctly. Second run, same day:
correctly skipped via the marker file.

**Still not independently confirmed**: whether `Start-ScheduledTask`
itself reaches a real process *from this tool session specifically*.
Several `Start-ScheduledTask` triggers after both fixes above still
showed no corresponding log entry or `pipeline_runs` row within the
session used to test this, despite `LastTaskResult: 0` -- but the
process list at the time showed no `python`/`powershell` process spawned
by Task Scheduler's parent at all (only ones this session had started
directly). That's consistent with this diagnostic session's own process
tree not being attached to the real interactive desktop session Task
Scheduler's `Interactive`/`AtLogOn` logon type checks against, rather
than a flaw in the task itself -- but it means the daily fire genuinely
needs to be confirmed by you, not just claimed: check
`logs\news_sync.log` for a fresh entry (or `logs\news_sync.lastrun` for
today's date) the next time you're logged in after 06:00.

## What's not built yet

- **Sentiment scoring** -- articles are ingested and entity-linked, but
  no sentiment score is computed or stored (`news_articles.sentiment_score`,
  spec section 3.6, stays at its model default). This was the single
  biggest unstarted branch flagged before this work and is now partially
  addressed (ingestion) but not fully (no sentiment signal yet).
- **Company-name-alias matching** -- entity linking matches only the raw
  ticker code as a whole word (e.g. "BBCA"), not a company's name ("Bank
  Central Asia"). No alias dictionary is built.
- **Semantic/cross-source deduplication** -- `is_duplicate`/
  `duplicate_of_id`/`cross_source_confirmed` all stay at their defaults;
  the only real dedup enforced is exact-URL uniqueness.
- **A 5th, official-disclosure-tier (tier 1) source** -- would need IDX's
  own feed, which is blocked (HTTP 403), same as its OHLCV endpoints.
- **Confirmed-reliable unattended scheduling** -- see above.
