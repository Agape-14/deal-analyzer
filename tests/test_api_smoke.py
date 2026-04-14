"""End-to-end API smoke: exercise every non-AI endpoint through the
FastAPI test client. Confirms routing, schema validation, CRUD, and
the data-integrity persistence paths work together.

AI-gated routes (/extract, /verify, /chat, /market-research) are
skipped — they require ANTHROPIC_API_KEY and a real network call.
"""

import pytest

pytestmark = pytest.mark.asyncio


async def _new_dev(client, name="Test GP"):
    r = await client.post("/api/developers", json={"name": name})
    assert r.status_code == 200
    return r.json()["id"]


async def _new_deal(client, name="Test Deal", **kwargs):
    payload = {"project_name": name, "property_type": "multifamily", **kwargs}
    r = await client.post("/api/deals", json=payload)
    assert r.status_code == 200
    return r.json()["id"]


# ---------- healthz ---------- #


async def test_healthz_reports_models_and_auth(client):
    r = await client.get("/api/healthz")
    assert r.status_code == 200
    body = r.json()
    assert "models" in body and "extract" in body["models"]
    assert "auth" in body
    assert "rate_limits" in body


# ---------- Developer CRUD ---------- #


async def test_developer_crud(client):
    dev = await _new_dev(client)
    r = await client.get("/api/developers")
    assert r.status_code == 200
    assert any(d["id"] == dev for d in r.json())
    r = await client.get(f"/api/developers/{dev}")
    assert r.status_code == 200
    r = await client.put(f"/api/developers/{dev}", json={"phone": "555"})
    assert r.status_code == 200
    r = await client.delete(f"/api/developers/{dev}")
    assert r.status_code == 200
    r = await client.get(f"/api/developers/{dev}")
    assert r.status_code == 404


# ---------- Deal CRUD + validation ---------- #


async def test_deal_create_rejects_bogus_status(client):
    r = await client.post("/api/deals", json={"project_name": "X", "status": "bogus"})
    assert r.status_code == 422


async def test_deal_create_rejects_missing_name(client):
    r = await client.post("/api/deals", json={"status": "reviewing"})
    assert r.status_code == 422


async def test_deal_put_updates_metrics(client):
    deal = await _new_deal(client)
    r = await client.put(
        f"/api/deals/{deal}",
        json={"metrics": {"deal_structure": {"ltv": 65}, "target_returns": {"target_irr": 15}}},
    )
    assert r.status_code == 200
    r = await client.get(f"/api/deals/{deal}")
    assert r.json()["metrics"]["deal_structure"]["ltv"] == 65


async def test_deal_detail_includes_quality_summary(client):
    deal = await _new_deal(client)
    await client.post(
        f"/api/deals/{deal}/fields/edit",
        json={"path": "deal_structure.ltv", "value": 65, "lock": True},
    )
    r = await client.get(f"/api/deals/{deal}")
    assert "quality" in r.json()
    assert r.json()["quality"]["manual"] == 1
    assert r.json()["quality"]["locked"] == 1


# ---------- Compare ---------- #


async def test_compare_rejects_too_many(client):
    r = await client.post("/api/deals/compare", json={"deal_ids": list(range(1, 10))})
    assert r.status_code == 422  # max_length 8


async def test_compare_returns_full_details(client):
    d1 = await _new_deal(client, "A")
    d2 = await _new_deal(client, "B")
    r = await client.post("/api/deals/compare", json={"deal_ids": [d1, d2]})
    assert r.status_code == 200
    deals = r.json()["deals"]
    assert len(deals) == 2


# ---------- Investments ---------- #


async def test_investment_irr_bounds(client):
    # 999% IRR should be rejected (upper bound = 300)
    r = await client.post(
        "/api/investments/",
        json={"project_name": "X", "amount_invested": 1, "projected_irr": 999},
    )
    assert r.status_code == 422


async def test_distribution_must_be_positive(client):
    # Create one investment and try to add a zero-dollar distribution.
    r = await client.post(
        "/api/investments/",
        json={"project_name": "X", "amount_invested": 1000},
    )
    inv_id = r.json()["id"]
    r = await client.post(
        f"/api/investments/{inv_id}/distributions",
        json={"date": "2024-01-01", "amount": 0},
    )
    assert r.status_code == 422


# ---------- Data integrity routes ---------- #


async def test_field_edit_lock_and_resolve(client):
    deal = await _new_deal(client)
    r = await client.post(
        f"/api/deals/{deal}/fields/edit",
        json={"path": "deal_structure.ltv", "value": 62, "lock": True},
    )
    assert r.status_code == 200

    r = await client.post(
        f"/api/deals/{deal}/fields/lock",
        json={"path": "deal_structure.ltv", "locked": False},
    )
    assert r.status_code == 200

    r = await client.post(
        f"/api/deals/{deal}/fields/resolve-conflict",
        json={"path": "deal_structure.ltv", "value": 64},
    )
    assert r.status_code == 200


async def test_validate_score_mathcheck_quality(client):
    deal = await _new_deal(client)
    await client.put(
        f"/api/deals/{deal}",
        json={
            "metrics": {
                "target_returns": {"target_irr": 15, "target_equity_multiple": 1.8},
                "deal_structure": {"ltv": 65, "hold_period_years": 5},
                "financial_projections": {"entry_cap_rate": 5.8, "exit_cap_rate": 6.2},
            }
        },
    )
    for path in ("validate", "math-check", "quality"):
        r = await client.get(f"/api/deals/{deal}/{path}")
        assert r.status_code == 200, f"{path} failed: {r.text}"
    r = await client.post(f"/api/deals/{deal}/score")
    assert r.status_code == 200


# ---------- Location ---------- #


async def test_location_manual_and_bounds(client):
    deal = await _new_deal(client)
    # Out-of-range lat rejected
    r = await client.post(
        f"/api/deals/{deal}/location/manual", json={"lat": 91, "lng": 0}
    )
    assert r.status_code == 422
    # Valid coords accepted
    r = await client.post(
        f"/api/deals/{deal}/location/manual",
        json={"lat": 30.27, "lng": -97.74},
    )
    assert r.status_code == 200
    r = await client.get(f"/api/deals/{deal}")
    body = r.json()
    assert body["lat"] == 30.27
    assert body["lng"] == -97.74


# ---------- Upload guards ---------- #


async def test_upload_rejects_non_pdf(client):
    deal = await _new_deal(client)
    # text/plain with a .txt filename
    r = await client.post(
        f"/api/deals/{deal}/documents/upload",
        files={"file": ("foo.txt", b"not a pdf", "text/plain")},
    )
    assert r.status_code == 415
