# Tests

```bash
# Run all tests
python -m pytest

# Single file
python -m pytest tests/test_data_integrity.py

# Single test
python -m pytest tests/test_validator.py::test_multifamily_flags_32pct_irr

# Verbose
python -m pytest -vv
```

## What's covered

| File | What it tests |
|---|---|
| `test_auth.py` | bcrypt hash/verify, login gate, public-path whitelist |
| `test_rate_limit.py` | Token-bucket allow/refill, per-bucket and per-key isolation |
| `test_data_integrity.py` | `smart_merge` preserves null-overwrites, locks, conflict detection, `stamp_verification`, quality counters, staleness flags |
| `test_validator.py` | Asset-class profiles (multifamily / development / land), property-type branching, LTV thresholds |
| `test_portfolio_analytics.py` | `xirr()` basic + the overflow regression fix |
| `test_api_smoke.py` | End-to-end API via FastAPI test client: healthz, CRUD, validation bounds, compare, field-edit/lock/resolve, location manual, upload MIME guard |

AI-gated paths (`/extract`, `/verify`, `/chat`, `/market-research`) are
deliberately not tested here — they require `ANTHROPIC_API_KEY` and
a real network round-trip. Mock tests for those would just be testing
the mock.

## CI

Runs from the repo root with no extra setup. The test fixtures use a
fresh SQLite file per test (via `tmp_path`) and set
`AUTH_DISABLED=1` so no credentials are needed.
