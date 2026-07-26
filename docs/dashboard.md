# Web dashboard (spec §25)

Status: a real, working Next.js dashboard (`apps/web`) consuming
`docs/api.md`'s read-only API. Three routes, verified end-to-end against
real production data, not a mockup.

## Stack, and why

Next.js 16 (App Router) + TypeScript + Tailwind, per the plan already
recorded in `apps/web/README.md` (spec §25). Server Components fetch the
backend directly (`fetch(..., { cache: "no-store" })`) on every request --
no client-side data-fetching library, since there's nothing to cache
client-side that the read-only API doesn't already own. This version of
Next.js (16.2.12) is materially different from earlier versions this
project's training data would assume (`params`/`searchParams` are now
`Promise`s that must be `await`ed, route-typed `PageProps<'/...'>`
helpers exist) -- the scaffold's own `AGENTS.md` flags this explicitly,
and the routing/data-fetching guides under
`apps/web/node_modules/next/dist/docs/` were read before writing any
route, not assumed from memory.

## Routes

- `/` -- company list (947 real companies), `q` search by ticker/name
  substring, offset-based pagination.
- `/companies/[ticker]` -- calls `/snapshot` and `/news`: recommendation
  (label, confidence, entry zone, guardrails incl. the new
  `recent_negative_sentiment` one), valuation (bear/base/bull/
  conservative), technical/fundamental-ratio/sector-relative-metric
  tables, and recent entity-linked news with its sentiment badge. Real
  404 page (`notFound()`) for an unknown ticker, not a blank/broken page.
- `/recommendations` -- the screener, filterable by label via query
  param, sorted by confidence (matching the API's own ordering).

## Real bug found live: a stale Docker container was silently answering requests

Testing `/` first returned a 500 from a `404` thrown by `lib/api.ts` --
confusing, since `curl` against the exact same API URL worked. Traced by
reproducing the identical `fetch()` call in a bare `node -e` script
(reproduced the 404 outside Next.js too, ruling out a Next-specific
cause), then `Get-NetTCPConnection -LocalPort 8000` -- which showed
**three** processes bound to port 8000 (`127.0.0.1`, `::1`, and `::`).
`docker-compose.yml`'s own `stock-model-api-1` container (built hours
earlier, before this session's API work existed) was still running and
squatting the wildcard/IPv6 bindings via Docker's port-forwarding
proxy -- Node's `fetch('http://localhost:...')` resolved to *that* stale
container instead of the manually-started dev `uvicorn` bound only to
`127.0.0.1`, explaining a real 404 (not a connection error) from
genuinely different, older code. Fixed by stopping the stale container
(`docker stop stock-model-api-1`) before testing -- the real, permanent
fix is keeping the compose-managed `api` service current via rebuilds,
not running an ad hoc second instance on the same port.

## Real end-to-end verification (2026-07-26)

Both `apps/api` (real `uvicorn`, real DB) and `apps/web` (`npm run dev`)
were run for real, then hit with real HTTP requests (not just unit
tests, since this project has none for a UI layer -- verification here
means exercising the actual running app):

- `/` -- real company list rendered (AADI/Adaro Andalan Indonesia, etc.),
  `?q=BBCA` search correctly narrows to one row.
- `/companies/BBCA` -- real recommendation (`HOLD`), real sector
  (`Financial Services`), real technical (`rsi_14`) and fundamental
  (`net_margin`) values rendered from the actual snapshot endpoint.
- `/companies/BCIC` -- real entity-linked article ("Laba Bank J Trust
  (BCIC) Anjlok...", CNBC Indonesia) with its real (`netral`) sentiment
  badge -- the same under-read-as-neutral result `docs/sentiment.md`
  already documents honestly, visible here rather than hidden.
- `/companies/ZZZNOTREAL` -- real 404 page.
- `/recommendations?label=HINDARI` -- correctly narrows to exactly the 4
  real companies with that label (EXCL, MPRO, SRAJ, EMAS), matching
  `docs/recommendation.md`'s recorded label distribution.
- `npm run lint` -- clean. `npm run build` -- compiles, type-checks, and
  prerenders all 4 routes with no errors.

## What's not built yet / known gaps

- **`docker compose up --build web` not verified end-to-end** -- the
  `web` service was added to `docker-compose.yml` and its config
  validated (`docker compose config`), and the Dockerfile follows the
  same proven pattern as `apps/api/Dockerfile`, but a full containerized
  build was not run: this session's Docker environment showed a very
  slow/stuck build (large existing disk usage, ~40GB of images/build
  cache) when rebuilding just the `api` image, and verification instead
  proceeded via `npm run dev` + a directly-run `uvicorn` process. Stated
  plainly as unverified, not claimed as tested.
- **No auth** -- matches `docs/api.md`'s own "no auth" gap; irrelevant
  for local/dev use, a real gap before any non-local deployment.
- **No charts** -- technical/valuation values are rendered as plain
  tables, not price/fair-value charts.
- **No client-side interactivity beyond basic forms** -- search and label
  filters are plain HTML forms/links causing full server re-renders, no
  `use client` components, debounced search, etc. Reasonable for a
  read-only research dashboard's first cut, not a hard technical limit.
