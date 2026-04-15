# Architecture

A tour of how Kenyon is put together, where each piece lives, and why
the tricky parts look the way they do.

## 1. Request lifecycle

```
Browser ──▶ Next.js (edge)
                │
                │  /api/* — same-origin rewrite
                ▼
         FastAPI (uvicorn)
                │
                ├── GZip (compress JSON ≥ 1 KB)
                ├── SecurityHeaders (HSTS / XFO / CSP-adjacent)
                ├── EnforceAuth (401 on protected /api/* without session)
                ├── SessionMiddleware (signed HttpOnly cookie)
                │
                ▼
           Route handler
                │
                ├── Pydantic validates + bounds the input
                ├── Depends(limit("ai"|"write"|"auth"|…)) — token bucket
                │
                ▼
           Service layer (pure-ish)
                │
                ▼
           SQLAlchemy async session
```

Middleware order matters: SessionMiddleware must run **before**
EnforceAuth so `request.session` is populated. `add_middleware`
registers in reverse (last-added = outermost), so they're added in
the file bottom-up.

## 2. Data-integrity model

Every metric on `deal.metrics` has a shadow entry on
`deal.metrics._provenance` keyed by dotted path (`deal_structure.ltv`)
with:

```ts
{
  source:        "extraction" | "verification" | "manual" | "calculated",
  source_doc_id: number,       // which uploaded doc this came from
  source_doc_name: string,
  source_page:   number | null, // parsed from AI's citation when possible
  extracted_at:  ISO timestamp,
  confidence:    0–100,         // from /verify when available
  status:        "extracted" | "confirmed" | "wrong" | "unverifiable"
                 | "calculated" | "missing" | "manual",
  conflict:      [{doc_id, doc_name, value}, …] | null,
  locked:        boolean,       // manually edited — untouchable by /extract
}
```

Rules enforced by `app/services/data_integrity.py`:

- **Null-safe merge.** `smart_merge(existing, incoming)` never
  overwrites a real value with null. A subsequent extraction that
  doesn't mention IRR keeps the previous IRR intact.
- **Locks win.** A manually-edited field is frozen against all
  future extractions.
- **Conflict detection.** When the same field comes back from
  multiple docs with different values (outside a 2% rounding
  tolerance), we keep every observation in `conflict` and emit a red
  validation flag. The UI shows a resolve dropdown.
- **Verification stamping.** `POST /{id}/verify` runs a second-pass
  AI audit; its per-field status lands on the same provenance tree.
- **Staleness.** `staleness_flags()` emits a yellow flag if the
  newest extraction is >60 days old OR if a newer document was
  uploaded but never re-extracted against.

## 3. Extraction pipeline

```
Upload
  │
  ▼
PyMuPDF text extraction per page (MIN_TEXT_CHARS gate)
  ├── text layer present → use it
  ├── empty page         → Tesseract OCR fallback at 200 DPI
  └── record page diagnostics (source, chars) on DealDocument
  │
  ▼
Tables via PyMuPDF find_tables() + images via page.get_images()
  │
  ▼
POST /api/deals/{id}/extract
  ├── per-doc extraction first (for conflict detection)
  ├── union extraction over all docs (for the actual merge)
  ├── Claude Opus 4.6, vision+text, max_tokens 8192
  │     prompt: 181-line schema + nulls-only-on-absent rules
  ├── smart_merge into existing deal.metrics (preserves, honors locks)
  ├── detect_conflicts → red flags + conflict entries in provenance
  ├── validate (Burke rules, asset-class aware)
  └── staleness flags re-computed

POST /api/deals/{id}/verify
  ├── Claude Opus 4.6 with page images (up to 10)
  ├── Returns audit_results[]: status + correct_value + source citation
  ├── stamp_verification() — writes status + confidence onto provenance
  └── optional auto_correct applies "wrong" → "correct_value"

GET /api/deals/{id}/quality
  └── Aggregates provenance into trust score + per-status counters
```

Model selection lives in `app/config.py` — every AI call is overridable
via env var, defaults pin the accuracy-critical paths to Opus 4.6.

## 4. Auth + session

- `POST /api/auth/login` validates credentials (bcrypt, with a constant
  0.5-second delay on failure to defeat timing attacks, and an 8-per-
  minute rate limit to defeat brute force).
- Success writes a `kenyon_session` cookie — HttpOnly, SameSite=lax,
  signed with `AUTH_SECRET`, 30-day TTL. Secure flag on when
  `SESSION_HTTPS_ONLY=1` (auto on Railway).
- `EnforceAuthMiddleware` rejects any `/api/*` without a valid session
  (except the whitelist: `/api/healthz`, `/api/auth/*`).
- Next.js `middleware.ts` redirects UI routes to `/login?next=…` when
  the cookie is missing — server-side the backend is still source of
  truth.
- Single-user by design: `AUTH_USERNAME` + `AUTH_PASSWORD_HASH` are
  env vars, not a user table.

## 5. Location intelligence

```
Deal row carries lat, lng, location_data (JSON cache, 7-day TTL)

GET /api/deals/{id}/location
  ├── cache hit within radius + TTL → return it
  ├── cache miss → geocode via Nominatim (1-req/sec, process lock)
  ├── Overpass query across 8 POI categories in parallel (sem=4)
  ├── HUD FMR lookup if HUD_API_TOKEN set
  └── persist on deal.location_data

POST /api/deals/{id}/location/manual
  └── user-placed coords; invalidates category cache
```

All free / unauthenticated upstream sources. Map engine is MapLibre GL
(open-source fork of Mapbox), tiles from CartoDB (dark / streets) or
Esri World Imagery (satellite). No API key required anywhere.

## 6. Rate limiting

`app/rate_limit.py` holds a process-local token bucket store keyed by
`(bucket_name, client_key)` where `client_key` is the session username
when available, else forwarded-IP. Five buckets:

| Bucket | Capacity | Refill (per min) | Routes |
|---|---|---|---|
| `ai` | 10 | 10 | /extract, /verify, /market-research, /chat |
| `upload` | 20 | 20 | /documents/upload |
| `write` | 60 | 60 | /score (other writes are cheap) |
| `read` | 300 | 300 | reserved |
| `auth` | 8 | 8 | /auth/login |

Responses include `X-RateLimit-*` headers and `Retry-After` on 429.

## 7. Database schema

Six tables, SQLAlchemy async, SQLite-or-Postgres via `DATABASE_URL`.

- **developers** — id, name, contact fields, track_record, notes,
  `deleted_at` (soft), created_at.
- **deals** — FK to developers, project info, metrics (JSON), scores
  (JSON), lat/lng + location_data (JSON), `deleted_at`, indexed
  `status`/`developer_id` for the pipeline queries.
- **deal_documents** — FK to deals (indexed), file_path, extracted_text,
  `extraction_quality` (JSON: per-page source + char count + quality
  score 0–100).
- **deal_chats** — FK to deals (indexed), role, content, created_at.
- **investments** — FK to deals (nullable + indexed), sponsor_name,
  amount_invested, projected / actual metrics, `deleted_at`, status,
  exit_date / exit_amount.
- **distributions** — FK to investments (indexed), date, amount,
  dist_type.
- **notifications** — kind / title / body / href / payload (JSON) /
  read_at / created_at (indexed).

Schema managed by Alembic — every change has a migration. Railway
runs `alembic upgrade head` before `uvicorn` on each deploy.

## 8. Frontend organization

Feature-sliced, not framework-sliced. Each domain concern has its own
folder under `web/src/components/`:

- `deal-detail/` — Overview / Metrics / Cashflow / Location / Documents /
  Analyst tabs, quality panel, integrity badge, conflict picker.
- `portfolio/` — hero KPIs, J-curve chart, allocation pies, position
  cards with sparklines, performers strip, add/distribution/exit
  modals.
- `compare/` — preset definitions, toolbar, deal picker, metrics
  table with Values / Winners / Deltas / Normalized modes, custom
  preset drawer.
- `developers/` — list + detail views, edit drawer.

Shared: `app-shell.tsx` conditional chrome, `app-header.tsx`,
`app-sidebar.tsx`, `command-palette.tsx`, `notifications-bell.tsx`,
`theme-provider.tsx`, `environment-banner.tsx`, `help-overlay.tsx`.

State lives:
- **URL** — tab selection, compare selection, preset choice, light
  filter state. Every view is bookmarkable.
- **React state** — transient UI (open/closed drawers, pin-drop mode).
- **Server** — everything persistent; refetched on `router.refresh()`.

Data fetching: `lib/api.ts` is a thin fetch wrapper that's aware of
server vs client context. On the server it pulls cookies from
`next/headers` and forwards them to the FastAPI internal URL so RSC
pages stay authenticated.

## 9. Testing strategy

`tests/` uses pytest + pytest-asyncio + FastAPI's test client. Fresh
SQLite per test via `tmp_path`. Auth disabled in the fixture for
API tests (dedicated `test_auth.py` covers credentials / bounds).

What's covered:
- `test_auth.py` — hash/verify, public-path whitelist
- `test_rate_limit.py` — token bucket semantics
- `test_data_integrity.py` — smart_merge null-preserve, lock,
  conflict detection, verification stamping, quality, staleness
- `test_validator.py` — asset-class profiles, LTV bands
- `test_portfolio_analytics.py` — `xirr` overflow regression
- `test_api_smoke.py` — full API surface: healthz, CRUD, bounds,
  compare limit, field-edit/lock/resolve, location bounds, upload MIME
- `test_soft_delete.py` — DELETE/restore/purge lifecycle
- `test_notifications.py` — emit-by-upload, mark-read flows

AI endpoints (`/extract`, `/verify`, `/chat`, `/market-research`) are
not unit tested — they require `ANTHROPIC_API_KEY` and a real network
call, and mocking them would just test the mock.

## 10. Deployment

See `DEPLOY.md`. Two-service Railway topology:

- `api` service (repo root) — Nixpacks picks up `railway.json` +
  `nixpacks.toml`. Runs `alembic upgrade head && uvicorn`. Attach a
  Volume at `/data` and set `DB_DIR=/data` so the SQLite file
  survives redeploys.
- `web` service (root dir: `web`) — runs `npm ci && npm run build`
  then `npm start`. Set `FASTAPI_URL` to Railway's private DNS for
  the api service so the web tier talks to it over the internal
  network (API never needs a public domain).

Environment banner on the frontend polls `/api/healthz` and surfaces
missing env vars directly to the user, so misconfigured deploys are
obvious before anyone clicks a button that would 503.
