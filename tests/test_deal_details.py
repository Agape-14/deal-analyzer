import pytest
pytestmark = pytest.mark.asyncio

async def test_detail_edits_check_revision_and_allow_clearing_sponsor_without_changing_financial_locks(client):
    sponsor = (await client.post("/api/developers", json={"name": "Details sponsor"})).json()["id"]
    deal = (await client.post("/api/deals", json={"project_name": "Draft", "developer_id": sponsor})).json()["id"]
    await client.post(f"/api/deals/{deal}/fields/edit", json={"path": "deal_structure.minimum_investment", "value": 25000, "lock": True})
    before = (await client.get(f"/api/deals/{deal}")).json()
    update = {"project_name": "Reviewed title", "developer_id": None, "status": "interested", "notes": "Evidence follow-up", "expected_revision": before["revision"]}
    assert (await client.put(f"/api/deals/{deal}", json=update)).status_code == 200
    assert (await client.put(f"/api/deals/{deal}", json=update)).status_code == 409
    after = (await client.get(f"/api/deals/{deal}")).json()
    assert after["developer_id"] is None and after["project_name"] == "Reviewed title"
    assert after["metrics"]["_locks"] == before["metrics"]["_locks"]
    assert after["minimum_investment"] == 25000
    assert (await client.put(f"/api/deals/{deal}", json={"developer_id": 999999})).status_code == 422
