# Kenyon Deal Analyzer

Institutional-grade real-estate deal analysis for a single operator.
Upload an offering memorandum, let Claude extract the metrics, verify
against the source PDFs, score against Burke-inspired rules, and
compare deals head-to-head. Track investments, distributions, and
portfolio performance. See competing apartments, amenities, and HUD
rent context on a satellite map.

```
┌────────── Next.js 15 (App Router) ──────────┐    ┌───── FastAPI ─────┐
│                                             │    │                   │
│  /             Dashboard + pipeline widgets │    │  /api/deals/*     │
│  /deals/[id]   Overview / Metrics /         │ ◀──▶  /api/investments │
│                Cashflow / Location /        │    │  /api/developers  │
│                Documents / Analyst          │    │  /api/auth/*      │
│  /portfolio    J-curve + positions          │    │  /api/chat        │
│  /compare      8 presets + custom           │    │  /api/reports/*   │
│  /developers   Sponsor book + detail        │    │  /api/notifications│
│                                             │    │                   │
│  ⌘K palette · ? shortcuts · Bell · Themes   │    │  SQLite + Alembic │
└─────────────────────────────────────────────┘    └───────────────────┘
             cookie auth (HttpOnly, Secure, SameSite=lax)
```

## Quickstart

```bash
# 1. Backend
python -m pip install -r requirements.txt
alembic upgrade head
python -m uvicorn app.main:app --port 8000

# 2. Frontend (separate terminal)
cd web
npm install
npm run dev          # → http://localhost:3000

# 3. Open the app
open http://localhost:3000
```

On first boot the app is **open** (no auth). To enable:

```bash
python -m app.auth hash YOUR_PASSWORD
# copy the $2b$... hash, then:
export AUTH_USERNAME=admin
export AUTH_PASSWORD_HASH='$2b$12$...'
export AUTH_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
python -m uvicorn app.main:app
```

For Railway deployment, see [`DEPLOY.md`](DEPLOY.md).

## Tech stack

**Backend** — FastAPI 0.x · SQLAlchemy async (aiosqlite) · Alembic ·
PyMuPDF + Tesseract for PDF / OCR · Anthropic SDK · httpx · bcrypt
(auth) · Starlette SessionMiddleware (cookie signing).

**Frontend** — Next.js 15 App Router · React 19 · TypeScript (strict) ·
Tailwind · Framer Motion · Recharts · MapLibre GL · Radix UI
primitives · Sonner (toasts) · cmdk (command palette).

**Services** — Anthropic Opus 4.6 (extract, verify) + Sonnet 4.6
(market research, chat) · OpenStreetMap Nominatim + Overpass (free) ·
HUD Fair Market Rent API (free) · Optional: Brave Search.

## Architecture

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for a deeper read. Highlights:

- **Data-integrity layer** — every extracted metric carries
  provenance (which doc, which page, when, verified-by-whom). Re-
  extraction can't overwrite a real value with null. Cross-document
  conflicts are flagged, not silently resolved. `smart_merge` in
  `app/services/data_integrity.py` is the single entry point.

- **Extraction pipeline** — upload → PyMuPDF text + OCR fallback for
  scanned pages → Claude (vision) fills the metric schema → validate
  (Burke rules, asset-class-aware) → score (7 weighted categories) →
  optional `verify` pass against source PDFs.

- **Rate limiting** — in-memory token buckets on AI / upload / auth
  paths. Keyed by session user when available, else client IP.

- **Location intelligence** — Nominatim geocodes the address, Overpass
  returns 8 POI categories in a radius, HUD gives zip-level rent
  context. All free, all optional, 7-day cache on the deal row.

## Environment

| Variable | Used for | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | extract / verify / chat / market | — |
| `AUTH_USERNAME` | login username | `admin` |
| `AUTH_PASSWORD_HASH` | bcrypt hash from `python -m app.auth hash ...` | — (auth off) |
| `AUTH_SECRET` | session cookie signing key (32+ chars) | ephemeral |
| `SESSION_HTTPS_ONLY` | cookie Secure flag | auto (`1` on Railway) |
| `DB_DIR` | where SQLite lives | repo root |
| `DATABASE_URL` | override to use Postgres etc. | — |
| `MODEL_EXTRACT` | Anthropic model for extraction | `claude-opus-4-6` |
| `MODEL_VERIFY` | model for verification | `claude-opus-4-6` |
| `MODEL_MARKET` | model for market research | `claude-sonnet-4-6` |
| `MODEL_CHAT` | model for analyst chat | `claude-sonnet-4-6` |
| `HUD_API_TOKEN` | enables rent context on the map | — (optional) |
| `BRAVE_API_KEY` | enables live search in `/market-research` | — (optional) |
| `LOG_LEVEL` | Python logging level | `INFO` |

## Development

```bash
# Run the full test suite (pytest + FastAPI test client)
python -m pytest                    # 56 tests in ~15s

# Add a migration
# 1) change app/models.py
alembic revision --autogenerate -m "what changed"
alembic upgrade head

# Frontend typecheck + build
cd web
npx tsc --noEmit
npx next build
```

Seed scripts: `scripts/seed-portfolio.sh` drops realistic test data
(3 sponsors, 5 investments, 37 distributions) into a running dev API.

## Repository layout

```
app/                  FastAPI app
  auth.py             bcrypt + session helpers + CLI (hash)
  config.py           model IDs, env probe
  rate_limit.py       token-bucket limiter
  security_headers.py HSTS / XFO / CSP middleware
  main.py             app + middleware stack + healthz
  database.py         SQLAlchemy async engine + init_db
  models.py           6 tables: developers / deals / deal_documents /
                      deal_chats / investments / distributions / notifications
  routers/            one file per resource (deals.py is the big one)
  services/           pure-ish business logic
    data_integrity.py smart_merge / conflicts / provenance / locks
    deal_extractor.py Anthropic extract pipeline
    deal_verifier.py  second-pass AI audit
    deal_scorer.py    7 weighted categories
    deal_validator.py Burke rules (asset-class aware)
    math_checker.py   deterministic arithmetic sanity
    cashflow_projector.py  per-deal cashflow timeseries
    waterfall_calculator.py LP/GP waterfall
    portfolio_analytics.py portfolio IRR + breakdowns
    pipeline_analytics.py  dashboard widget data
    pdf_extractor.py  PyMuPDF + OCR
    location_intelligence.py Nominatim + Overpass + HUD
    market_data.py    Brave + Claude market synthesis
    notifications.py  emit / mark-read helpers

alembic/              migrations (env.py uses our Base + DATABASE_URL)
tests/                56 tests — services + API smoke

web/src/              Next.js app
  app/                App Router routes (+ loading / error / not-found)
  components/         Feature modules, one per domain concern
  lib/                types + api client + formatters
  middleware.ts       session-cookie redirect to /login
```

## Status

All phases 1–17 shipped. See git log on `claude/build-deal-analyzer-*`
for the chronological walkthrough. The branch is production-ready:

- 56 automated tests, green on every push
- Alembic migrations for every schema change
- Auth, rate limit, security headers, path-traversal guards
- Undo for every destructive action
- Dark + light themes
- Mobile nav + responsive layouts
- First-run welcome + ⌘K + ? shortcuts
