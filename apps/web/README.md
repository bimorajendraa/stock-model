# Web dashboard (spec §25)

Status: real, working Next.js App Router dashboard, built once
`docs/api.md`'s API had real recommendation/valuation/technical/
fundamental/sentiment data to serve. See `docs/dashboard.md` for what was
verified and how.

Three routes, each a Server Component that `fetch()`es `apps/api` at
request time (`cache: "no-store"` -- always current, never stale):

- `/` -- company list, ticker/name search, pagination.
- `/companies/[ticker]` -- the snapshot page: recommendation, valuation,
  technical/fundamental/sector-relative values, recent news + sentiment.
- `/recommendations` -- the recommendation screener, filterable by label.

## Local dev

```bash
cp .env.example .env.local   # API_BASE_URL, defaults to http://localhost:8000
npm install
npm run dev
```

Requires `apps/api` running separately (`docker compose up -d api`, or
`uvicorn apps.api.main:app` directly) -- this app has no data of its own.

## Stack

Next.js 16 (App Router, Server Components) + TypeScript + Tailwind CSS.
No client-side data-fetching library (SWR/React Query) -- every page is
server-rendered per request directly against the read-only API, so
there's no client-side cache to manage.
