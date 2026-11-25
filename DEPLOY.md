# Deploying to Railway

This repo is structured for a **two-service deploy** on Railway:

1. **`api`** — FastAPI, built from the repo root.
2. **`web`** — Next.js, built from the `web/` subdirectory.

Both services build with Railpack. Next.js proxies API calls over Railway's
private network. The Cloudflare Tunnel connects to the private web service,
and Cloudflare Access protects the application hostname.

## One-time setup

1. Create a new Railway project.
2. Add the **API service**:
   - New Service → Deploy from GitHub repo → pick this repo.
   - Root directory: **(leave blank — repo root)**.
   - Select the Railpack builder and clear any legacy Config File path.
     The root `railpack.json` installs the locked Python 3.12 dependencies,
     runs regression tests against a build-only database, and includes
     Tesseract and Poppler in the runtime image.
   - Set the health check to `/api/healthz/ready` with a 60-second timeout.
     The start command in `railpack.json` applies Alembic migrations before
     launching `start.py`. Set `PORT=8000` to match the private web target.
   - Variables to set:
     - `PAID_REVIEW_ENABLED=0` — keep the legacy Anthropic review paused.
     - `DEAL_REVIEW_PROVIDER=codex` — start with **Review with Codex** in Documents. Select **GPT-6 Astra** with **Extra High** reasoning in Codex when available. The user imports the cited result and approves the proposed values.
     - For optional API reviews, set `DEAL_REVIEW_PROVIDER=openai` and `OPENAI_API_KEY` on the API service. Use a project key from the organization linked to the included credits. Codex remains the first option, and **Review options** contains the manual API action.
     - `DEAL_REVIEW_MAX_USD=10` — adjustable per-request budget for GPT-6 Astra at Extra High reasoning. Set a positive whole dollar amount. The app counts input tokens first and accounts for long-context rates. The default is $10, with no silent truncation or lower-model fallback.
     - `DEAL_REVIEW_AUTO_AFTER_UPLOAD=0` — uploads are read locally for the Codex packet. Set to `1` only if you want to queue OpenAI reviews automatically once that provider is configured.
     - `DB_DIR=/data` — where SQLite lives; see volume step.
       Uploaded PDFs also go here (`/data/uploads/`) by default, so
       they survive redeploys. Override with `UPLOADS_DIR` if you
       want a separate mount for file storage.
     - **Auth** (required for real deploy — without these the app is public):
       - `AUTH_USERNAME=admin` (pick your login name)
       - `AUTH_PASSWORD_HASH=<bcrypt>` — generate with
         `python -m app.auth hash <your-password>` and paste the output.
         Don't put the plain password in env — only the hash.
       - `AUTH_SECRET=<random>` — `python -c 'import secrets; print(secrets.token_urlsafe(48))'`
         Signs the session cookie. Must be 16+ chars. A restart with a
         different secret logs everyone out.
       - `AUTH_DISABLED=1` — set ONLY for local dev to turn auth off.
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
   - Select the Railpack builder and clear any legacy Config File path.
     `web/railpack.json` selects Node 22 and starts the built Next.js app
     on a dual-stack listener. Set `PORT=3000` to match the tunnel target.
   - Set the health check to `/login` with a 60-second timeout.
   - Variables to set:
     - `FASTAPI_URL=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000`
       (This uses Railway's reference-variable syntax — replace `api` with
       whatever you named your API service. The web server fetches the API
       over the private network, never the public internet.)

## Domain

- Route the application hostname through Cloudflare Access and the
  Cloudflare Tunnel to the web service's Railway private address on port
  3000. Keep API and web free of public Railway domains and TCP proxies.

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
