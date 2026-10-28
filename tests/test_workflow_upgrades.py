"""HTTP regression coverage for valuations, stable links and source lookup."""
from datetime import date

import pytest

pytestmark = pytest.mark.asyncio


async def test_linked_terms_are_revision_guarded_and_sponsor_renames_retain_positions(client):
    sponsor = (await client.post("/api/developers", json={"name": "Original sponsor"})).json()["id"]
    deal_id = (await client.post("/api/deals", json={"project_name": "Linked", "developer_id": sponsor})).json()["id"]
    deal = (await client.get(f"/api/deals/{deal_id}")).json()
    base = {"deal_id": deal_id, "amount_invested": 1000, "investment_date": "2024-01-01"}
    assert (await client.post("/api/investments/", json=base | {"expected_analysis_version": 999})).status_code == 409
    response = await client.post("/api/investments/", json=base | {"expected_analysis_version": deal["analysis"]["version"], "expected_analysis_input_hash": deal["analysis"]["input_hash"]})
    assert response.status_code == 200, response.text
    investment_id = response.json()["id"]
    await client.put(f"/api/developers/{sponsor}", json={"name": "Renamed sponsor"})
    saved = (await client.get(f"/api/investments/{investment_id}")).json()
    assert saved["developer_id"] == sponsor and saved["sponsor_name"] == "Renamed sponsor"
    assert saved["source_analysis_version"] == deal["analysis"]["version"]


async def test_api_valuations_are_paired_and_exits_reconcile_across_endpoints(client):
    result = await client.post("/api/investments/", json={"project_name": "Reconciled", "amount_invested": 1000, "investment_date": "2024-01-01"})
    investment_id = result.json()["id"]
    path = f"/api/investments/{investment_id}"
    assert (await client.put(path, json={"residual_value": 1100})).status_code == 422
    assert (await client.put(path, json={"residual_value": 1100, "valuation_date": "2025-01-01"})).status_code == 200
    assert (await client.get(path + "/performance")).json()["tvpi"] == 1.1
    for amount, kind in ((100, "cash_flow"), (1200, "sale_proceeds")):
        assert (await client.post(path + "/distributions", json={"date": "2025-01-01", "amount": amount, "dist_type": kind})).status_code == 200
    assert (await client.put(path, json={"status": "exited", "exit_date": "2025-01-01", "exit_amount": 1200})).status_code == 200
    summary = (await client.get("/api/investments/portfolio")).json()
    analytics = (await client.get("/api/investments/portfolio/analytics")).json()["summary"]
    assert summary["total_returned"] == analytics["total_returned"] == 1300
    assert summary["dpi"] == analytics["tvpi"] == 1.3


async def test_source_lookup_has_locations_and_does_not_accept_document_claims(client):
    deal_id = (await client.post("/api/deals", json={"project_name": "Lookup"})).json()["id"]
    upload = await client.post(f"/api/deals/{deal_id}/documents/upload", files={"file": ("terms.csv", b"Metric,Value\nManagement fee,1%\n", "text/csv")})
    assert upload.status_code == 200, upload.text
    doc_id = upload.json()["id"]
    # Read the stored synthetic text, without invoking financial extraction.
    from app.database import async_session
    from app.models import DealDocument
    async with async_session() as db:
        doc = await db.get(DealDocument, doc_id)
        doc.extracted_text = "--- Sheet: Terms ---\nA1=Management fee | B1=1%"
        await db.commit()
    search = (await client.get(f"/api/chat/search?q=fees&deal_id={deal_id}")).json()
    assert search["hits"][0]["document_id"] == doc_id and search["hits"][0]["sheet"] == "Terms"
    excerpt = (await client.get(f"/api/deals/documents/{doc_id}/excerpt?sheet=Terms&cell=B1&expected_hash=stale")).json()
    assert "B1=1%" in excerpt["text"] and not excerpt["hash_matches"]
    answer = (await client.post("/api/chat", json={"deal_id": deal_id, "message": "What fees apply?"})).json()
    assert "Reported source excerpts" in answer["response"]
    assert answer["message"]["references"][0]["state"] == "reported"
