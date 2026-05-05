# Deal Analyzer App

FastAPI dashboard for tracking real estate deals, extracting metrics from offering documents, scoring opportunities, comparing deals, and tracking portfolio investments.

## Local run

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Environment variables

- `ANTHROPIC_API_KEY`: required for AI extraction, verification, and deal chat.
- `DATABASE_URL`: optional. Defaults to local SQLite at `deal_analyzer.db`. Railway/Postgres URLs are supported.

## Railway deploy

The repo includes:

- `Procfile` for generic process startup.
- `railway.json` with the `uvicorn` start command and `/health` health check.
- `runtime.txt` pinning Python 3.12.

For persistent production data, add a Railway Postgres service and set `DATABASE_URL` to its connection string. Without `DATABASE_URL`, the app runs on SQLite inside the deployment filesystem, which is not a good long-term production store.

## Health check

`GET /health` returns a small JSON status payload for uptime checks and Railway health verification.
