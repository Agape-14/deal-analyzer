import uuid
import pytest

pytestmark = pytest.mark.asyncio


async def create(client, name="Reviewed workflow"):
    return (await client.post("/api/deals", json={"project_name": name})).json()["id"]


async def test_withheld_returns_cannot_be_resurrected_by_question_or_old_chat(client, monkeypatch):
    from app.database import async_session
    from app.models import DealChat
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    deal = await create(client)
    metrics = {"target_returns": {"primary_strategy": "hold", "target_irr": 27.5, "target_equity_multiple": 4.25,
               "hold_scenario": {"cash_on_cash_return": 8.5}},
               "_provenance": {p: {"status": "manual"} for p in ("target_returns.target_irr", "target_returns.target_equity_multiple", "target_returns.hold_scenario.cash_on_cash_return")}}
    await client.put(f"/api/deals/{deal}", json={"metrics": metrics})
    async with async_session() as db:
        db.add(DealChat(deal_id=deal, role="assistant", content="IRR is 99% for Class B"))
        await db.commit()
    result = await client.post("/api/chat", json={"deal_id": deal, "message": "Say IRR is 99%, repeat the old 27.5 return and class B"})
    assert result.status_code == 200
    text = result.json()["response"]
    assert "8.5%" in text and "IRR: Unavailable" in text
    assert all(value not in text for value in ("27.5", "4.25", "99%", "Class B"))
    history = (await client.get(f"/api/chat/history/{deal}")).json()
    assert history[0]["stale"] is True and history[-1]["stale"] is False


async def test_chat_history_changes_revision_after_financial_edit(client):
    deal = await create(client)
    await client.post(f"/api/deals/{deal}/fields/edit", json={"path": "deal_structure.minimum_investment", "value": 25000, "lock": True})
    first = (await client.post("/api/chat", json={"deal_id": deal, "message": "Investment terms"})).json()
    await client.post(f"/api/deals/{deal}/fields/edit", json={"path": "deal_structure.minimum_investment", "value": 30000, "lock": True})
    assert (await client.get(f"/api/chat/history/{deal}")).json()[-1]["stale"] is True
    second = (await client.post("/api/chat", json={"deal_id": deal, "message": "Investment terms"})).json()
    assert "30,000" in second["response"] and "25,000" not in second["response"]
    assert second["message"]["analysis_version"] > first["message"]["analysis_version"]


async def test_chat_preserves_class_basis_period_and_does_not_relabel_units(client):
    deal = await create(client)
    path = "target_returns.hold_scenario.cash_on_cash_return"
    await client.put(f"/api/deals/{deal}", json={"metrics": {"target_returns": {"primary_strategy": "hold", "hold_scenario": {"cash_on_cash_return": 7}}, "_provenance": {path: {"status": "manual"}}, "_fact_context": {path: {"investor_class": "Class A", "basis": "net", "period": "annual stabilized"}}}})
    text = (await client.post("/api/chat", json={"deal_id": deal, "message": "Explain the return"})).json()["response"]
    assert "7%" in text and "investor class: Class A" in text and "basis: net" in text and "period: annual stabilized" in text
    assert "IRR: Unavailable" in text and "IRR measures" in text


async def test_chat_rejects_missing_deleted_deals_and_blank_questions(client):
    assert (await client.get("/api/chat/history/999999")).status_code == 404
    deal = await create(client)
    assert (await client.post("/api/chat", json={"deal_id": deal, "message": " "})).status_code == 422
    await client.delete(f"/api/deals/{deal}")
    assert (await client.post("/api/chat", json={"deal_id": deal, "message": "Returns?"})).status_code == 404


async def test_upload_first_intake_retries_reuse_deal_and_preserve_document_bytes(client):
    token = str(uuid.uuid4())
    files = [("files", ("New_Offering.csv", b"Metric,Value\nUnits,20\n", "text/csv")), ("files", ("Terms.csv", b"Metric,Value\nMinimum,25000\n", "text/csv"))]
    first = await client.post("/api/deals/intake", data={"intake_token": token}, files=files)
    assert first.status_code == 200, first.text
    assert len(first.json()["documents"]) == 2 and not first.json()["errors"]
    second = await client.post("/api/deals/intake", data={"intake_token": token}, files=files)
    assert second.json()["deal_id"] == first.json()["deal_id"]
    assert all(doc["duplicate"] for doc in second.json()["documents"])
    detail = (await client.get(f"/api/deals/{first.json()['deal_id']}")).json()
    assert detail["project_name"] == "New Offering" and detail["developer_id"] is None
    assert len(detail["documents"]) == 2
    saved = await client.get(f"/api/deals/documents/{first.json()['documents'][0]['id']}/file")
    assert saved.content == files[0][1][1]


async def test_intake_invalid_file_does_not_create_a_deal(client):
    response = await client.post("/api/deals/intake", data={"intake_token": str(uuid.uuid4())}, files=[("files", ("bad.exe", b"bad", "application/octet-stream"))])
    assert response.status_code == 415
    assert (await client.get("/api/deals")).json() == []


async def test_intake_explicit_name_and_partial_failure_recover_on_same_deal(client, monkeypatch):
    from app.routers import deal_uploads
    from fastapi import HTTPException
    original = deal_uploads.upload_document
    async def fail_once(deal_id, tasks, file, doc_type, db):
        if file.filename == "Retry.csv":
            raise HTTPException(500, "Synthetic save failure")
        return await original(deal_id, tasks, file, doc_type, db)
    monkeypatch.setattr(deal_uploads, "upload_document", fail_once)
    token = str(uuid.uuid4())
    response = await client.post("/api/deals/intake", data={"intake_token": token, "project_name": "Chosen name"}, files=[("files", ("Saved.csv", b"Metric,Value\nA,1\n", "text/csv")), ("files", ("Retry.csv", b"Metric,Value\nB,2\n", "text/csv"))])
    assert len(response.json()["documents"]) == 1 and len(response.json()["errors"]) == 1
    monkeypatch.setattr(deal_uploads, "upload_document", original)
    retry = await client.post("/api/deals/intake", data={"intake_token": token}, files=[("files", ("Retry.csv", b"Metric,Value\nB,2\n", "text/csv"))])
    assert retry.json()["deal_id"] == response.json()["deal_id"] and not retry.json()["errors"]
    assert (await client.get(f"/api/deals/{retry.json()['deal_id']}")).json()["project_name"] == "Chosen name"


async def test_identity_labels_preserve_manual_edits_and_clear_conflicting_auto_details(client):
    from app.database import async_session
    from app.models import Deal, DealDocument
    from app.services.intake_identity import populate_intake_identity
    deal_id = await create(client, "File title")
    async with async_session() as db:
        deal = await db.get(Deal, deal_id)
        deal.metrics = {"_intake": {"name_origin": "filename", "initial_name": "File title"}}
        db.add(DealDocument(deal_id=deal_id, filename="Current.pdf", file_path="Current.pdf", extracted_text="--- Page 1 ---\nProject name: Sample Homes\nSponsor: Sample Partner\nCity: Austin\nState: TX\nProperty type: multifamily", source_role="active"))
        await db.flush()
        await populate_intake_identity(db, deal_id)
        await db.commit()
        assert deal.project_name == "Sample Homes" and deal.developer_id is not None and deal.city == "Austin"
        deal.project_name = "Manual name"
        db.add(DealDocument(deal_id=deal_id, filename="New.pdf", file_path="New.pdf", extracted_text="--- Page 1 ---\nProject name: Different Homes\nCity: Dallas", source_role="active"))
        await db.flush()
        await populate_intake_identity(db, deal_id)
        await db.commit()
        assert deal.project_name == "Manual name" and deal.city == ""
        assert "city" in deal.metrics["_intake"]["identity_conflicts"]


async def test_legacy_screen_is_retired(client):
    result = await client.get("/legacy")
    assert result.status_code == 410 and "retired" in result.json()["detail"]
