# Deploying to Railway

This repo is structured for a **two-service deploy** on Railway:

1. **`api`** — FastAPI, built from the repo root.
2. **`web`** — Next.js, built from the `web/` subdirectory.

Both services auto-deploy from the same branch. The Next.js service proxies
API calls server-side via Railway's private network, so only the web service
needs a public domain.

## One-time setup

1. Create a new Railway project.
2. Add the **API service**:
   - New Service → Deploy from GitHub repo → pick this repo.
   - Root directory: **(leave blank — repo root)**.
   - Railway auto-detects `railway.json` at the root, which references
     `nixpacks.toml` for Python 3.11 + Tesseract + Poppler.
   - Variables to set:
     - `ANTHROPIC_API_KEY` — for AI scoring / chat.
     - `DB_DIR=/data` — where SQLite lives; see volume step.
     - **(optional)** Model overrides — defaults are optimized for accuracy.
       Only set these if you want to tune cost / latency:
       - `MODEL_EXTRACT` (default `claude-opus-4-6`) — metric extraction
       - `MODEL_VERIFY` (default `claude-opus-4-6`) — forensic verification
       - `MODEL_MARKET` (default `claude-sonnet-4-6`) — market research synthesis
       - `MODEL_CHAT` (default `claude-sonnet-4-6`) — analyst chat panel
       - For a cheap / fast chat, set `MODEL_CHAT=claude-haiku-4-5-20251001`.
       `GET /api/healthz` returns the live assignment so you can confirm.
   - Volumes: attach a Railway Volume at mount path **`/data`** so the
     SQLite file survives redeploys. (When you later move to Postgres,
     set `DATABASE_URL` and the volume becomes unused.)
3. Add the **Web service**:
   - New Service → Deploy from GitHub repo → same repo.
   - Root directory: **`web`** (this is the critical bit).
   - Railway will use `web/railway.json` which runs `npm ci && npm run build`
     then `npm start`.
   - Variables to set:
     - `FASTAPI_URL=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000`
       (This uses Railway's reference-variable syntax — replace `api` with
       whatever you named your API service. The web server fetches the API
       over the private network, never the public internet.)

## Domain

- Add the custom domain (e.g. `deals.conpulseai.com` or `app.conpulseai.com`)
  to the **web service only**.
- Railway provisions SSL automatically once your CNAME resolves.
- For the apex `conpulseai.com`, use Railway's ALIAS/ANAME support or a
  redirect from a root provider (Cloudflare Origin Rules, Vercel, etc.).

## Production DB recommendation

SQLite + a Railway Volume is fine for a single-user dashboard. When you want
concurrent writes / backups / replication:

1. Add a Railway Postgres plugin.
2. Copy the `DATABASE_URL` from the plugin into the API service variables.
3. Swap `aiosqlite` for `asyncpg` in `requirements.txt` and change the URL
   scheme to `postgresql+asyncpg://...`.

`app/database.py` already honors `DATABASE_URL` — no code change needed for
the swap beyond the driver.

## Local verification before deploying

```bash
# Terminal 1
python -m uvicorn app.main:app --port 8000

# Terminal 2
cd web
npm install
npm run build
npm start          # → http://localhost:3000
```

Healthchecks:
```bash
curl http://localhost:8000/api/healthz   # {"status":"ok"}
curl http://localhost:3000/              # renders dashboard
curl http://localhost:3000/legacy        # legacy UI via proxy
```
