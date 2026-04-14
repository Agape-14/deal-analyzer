"""Soft-delete / restore / purge behavior for Deal, Developer, Investment."""

import pytest

pytestmark = pytest.mark.asyncio


# ---------- Deal ---------- #


async def test_deal_soft_delete_hides_from_list_and_get(client):
    r = await client.post("/api/deals", json={"project_name": "Doomed"})
    deal_id = r.json()["id"]

    # Alive — appears in list
    r = await client.get("/api/deals")
    assert any(d["id"] == deal_id for d in r.json())

    # Soft-delete
    r = await client.delete(f"/api/deals/{deal_id}")
    assert r.status_code == 200
    assert "trash" in r.json()["message"].lower()

    # Gone from list and detail
    r = await client.get("/api/deals")
    assert not any(d["id"] == deal_id for d in r.json())
    r = await client.get(f"/api/deals/{deal_id}")
    assert r.status_code == 404

    # But present in ?trash=true
    r = await client.get("/api/deals?trash=true")
    assert any(d["id"] == deal_id for d in r.json())


async def test_deal_restore_brings_it_back(client):
    r = await client.post("/api/deals", json={"project_name": "Resurrect Me"})
    deal_id = r.json()["id"]
    await client.delete(f"/api/deals/{deal_id}")
    r = await client.post(f"/api/deals/{deal_id}/restore")
    assert r.status_code == 200
    r = await client.get(f"/api/deals/{deal_id}")
    assert r.status_code == 200


async def test_deal_purge_only_after_trash(client):
    r = await client.post("/api/deals", json={"project_name": "Purgable"})
    deal_id = r.json()["id"]
    # Purging a live deal should fail with 409
    r = await client.delete(f"/api/deals/{deal_id}/purge")
    assert r.status_code == 409
    # Trash first, then purge
    await client.delete(f"/api/deals/{deal_id}")
    r = await client.delete(f"/api/deals/{deal_id}/purge")
    assert r.status_code == 200
    # Actually gone
    r = await client.get(f"/api/deals?trash=true")
    assert not any(d["id"] == deal_id for d in r.json())


# ---------- Developer ---------- #


async def test_developer_soft_delete_lifecycle(client):
    r = await client.post("/api/developers", json={"name": "Gone Inc"})
    dev_id = r.json()["id"]

    r = await client.delete(f"/api/developers/{dev_id}")
    assert r.status_code == 200
    r = await client.get(f"/api/developers/{dev_id}")
    assert r.status_code == 404
    r = await client.post(f"/api/developers/{dev_id}/restore")
    assert r.status_code == 200
    r = await client.get(f"/api/developers/{dev_id}")
    assert r.status_code == 200


# ---------- Investment ---------- #


async def test_investment_soft_delete_excludes_from_portfolio_analytics(client):
    r = await client.post(
        "/api/investments/",
        json={"project_name": "A", "amount_invested": 100_000},
    )
    inv_a = r.json()["id"]
    r = await client.post(
        "/api/investments/",
        json={"project_name": "B", "amount_invested": 50_000},
    )
    inv_b = r.json()["id"]

    # Both counted
    r = await client.get("/api/investments/portfolio/analytics")
    assert r.json()["summary"]["investment_count"] == 2

    # Trash one
    await client.delete(f"/api/investments/{inv_a}")

    # Only the survivor is counted
    r = await client.get("/api/investments/portfolio/analytics")
    assert r.json()["summary"]["investment_count"] == 1

    # PUT on a trashed investment 404s
    r = await client.put(f"/api/investments/{inv_a}", json={"notes": "hi"})
    assert r.status_code == 404

    # Restore brings it back into analytics
    r = await client.post(f"/api/investments/{inv_a}/restore")
    assert r.status_code == 200
    r = await client.get("/api/investments/portfolio/analytics")
    assert r.json()["summary"]["investment_count"] == 2
