# Kenyon Deal Analyzer — Web

Next.js 15 + TypeScript + Tailwind + shadcn-style primitives. This is the
modern frontend that will gradually replace the legacy vanilla-JS UI.

## Develop

```bash
# Terminal 1 — FastAPI backend (from repo root)
python3 -m uvicorn app.main:app --port 8000

# Terminal 2 — Next.js (from web/)
cd web
npm install
npm run dev
```

Open http://localhost:3000. The Next.js server proxies:

- `/api/*` → FastAPI API
- `/legacy` and `/legacy/*` → the old UI
- `/static/*` → the legacy static assets (only used by `/legacy`)

The legacy UI stays available at `/legacy` during the migration.

## Build & run

```bash
npm run build
npm start
```

## Type generation

Once the backend is running, regenerate the OpenAPI types:

```bash
npm run generate:api
```

This writes `src/lib/api-types.ts`. For now we hand-write narrow types in
`src/lib/types.ts` — we'll migrate to the generated types as endpoints
stabilize.

## Structure

```
src/
  app/                     # Next.js App Router routes
    layout.tsx             # Root shell (sidebar + header + toaster)
    page.tsx               # Dashboard ("Deals")
    deals/[id]/            # Deal detail (stub)
    compare/               # Compare page (stub)
    developers/            # Developers page (stub)
    portfolio/             # Portfolio page (stub)
    globals.css            # Design tokens + dark theme
  components/
    app-sidebar.tsx        # Collapsible side nav
    app-header.tsx         # Top bar with search + actions
    deal-card.tsx          # Deal tile with animated score ring
    stat-card.tsx          # Stat tile with ticker animation
    motion.tsx             # FadeIn, Stagger, AnimatedNumber, HoverTilt
    construction.tsx       # "Coming soon" panel for stub routes
    ui/
      button.tsx
      card.tsx
      skeleton.tsx
  lib/
    api.ts                 # fetch wrapper (server + client aware)
    types.ts               # Hand-written domain types
    utils.ts               # cn, fmtMoney, fmtPct, fmtMultiple
```

## Design system notes

- Dark-default, near-black base, sky-blue primary.
- All financial figures use `tabular-nums` so decimals line up.
- Component motion uses springs (Framer Motion) with consistent easing:
  `cubic-bezier(0.22, 1, 0.36, 1)` for entries, spring for layout.
- Focus rings are visible but quiet; tap-highlight disabled.
- Elevation is built from layered surface tokens (no heavy shadows).
