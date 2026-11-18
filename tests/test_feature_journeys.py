"""Real HTTP/database/export coverage using synthetic deals, never live data."""
import io
import zipfile

import fitz
import openpyxl
import pytest

pytestmark = pytest.mark.asyncio


async def new_deal(client, name):
    response = await client.post("/api/deals", json={"project_name": name, "property_type": "multifamily"})
    assert response.status_code == 200
    return response.json()["id"]


@pytest.mark.parametrize("endpoint", ["compare", "compare/export"])
async def test_comparison_rejects_duplicate_missing_and_deleted_deals(client, endpoint):
    a, b = await new_deal(client, "A"), await new_deal(client, "B")
    url = "/api/deals/" + endpoint
    assert (await client.post(url, json={"deal_ids": [a, a]})).status_code == 400
    assert (await client.post(url, json={"deal_ids": [a, 99999]})).status_code == 404
    await client.delete(f"/api/deals/{b}")
    assert (await client.post(url, json={"deal_ids": [a, b]})).status_code == 404


async def test_return_values_agree_in_detail_compare_and_exports(client):
    a, b = await new_deal(client, "A & B <Fund>"), await new_deal(client, "Sale Deal")
    metrics = {
        "target_returns": {"primary_strategy": "hold", "target_irr": 22,
            "hold_scenario": {"cash_on_cash_return": 8},
            "sale_scenario": {"sale_irr": 22, "sale_equity_multiple": 2.4, "is_hypothetical": True}},
        "deal_structure": {"ltv": 60},
        "_provenance": {"target_returns.hold_scenario.cash_on_cash_return": {"status": "manual", "verification_note": "Project model, page 4."}},
        "_fact_context": {"target_returns.hold_scenario.cash_on_cash_return": {
            "investor_class": "Class B", "basis": "net", "period": "Year 2 after stabilization",
        }},
    }
    await client.put(f"/api/deals/{a}", json={"metrics": metrics, "scores": {"overall": None}, "notes": "A < B & C"})
    await client.put(f"/api/deals/{b}", json={"metrics": {"target_returns": {"target_irr": 15}, "deal_structure": {"ltv": 80}}})
    detail = (await client.get(f"/api/deals/{a}")).json()
    assert detail["target_irr"] is None
    assert detail["target_equity_multiple"] is None
    comparison = (await client.post("/api/deals/compare", json={"deal_ids": [b, a]})).json()["deals"]
    assert [d["id"] for d in comparison] == [b, a]
    assert comparison[1]["target_irr"] is None
    xlsx = await client.post("/api/deals/compare/export", json={"deal_ids": [b, a]})
    assert xlsx.status_code == 200
    sheet = openpyxl.load_workbook(io.BytesIO(xlsx.content)).active
    rows = {row[0].value: row for row in sheet.iter_rows() if row[0].value}
    assert rows["Target IRR"][2].value is None
    assert rows["Cash-on-Cash"][2].value == 8
    assert "Class B" in rows["Cash-on-Cash Context"][2].value
    assert "Year 2 after stabilization" in rows["Cash-on-Cash Context"][2].value
    assert "Project model, page 4." in rows["Cash-on-Cash Evidence"][2].value
    assert rows["LTV"][1].fill.fill_type is None  # High leverage is not a winner.
    pdf = await client.get(f"/api/reports/deal/{a}/pdf")
    assert pdf.status_code == 200
    with fitz.open(stream=pdf.content, filetype="pdf") as document:
        text = "".join(page.get_text() for page in document)
    assert "22.00%" not in text
    assert "8.00%" in text
    assert "Class B" in text
    assert "Calculation basis: net" in text
    assert "Year 2 after stabilization" in " ".join(text.split())
    assert "Project model, page 4." in text
    assert "Not scored" in text
    assert "A < B & C" in text


async def test_reviewed_return_scope_and_withholding_reach_all_outputs(client):
    from app.database import async_session
    from app.models import DealDocument

    deal, comparison = await new_deal(client, "Hold terms"), await new_deal(client, "Comparison")
    url = f"/api/deals/{deal}"
    path = "target_returns.hold_scenario.cash_on_cash_return"
    quote = "13.0% annual cash-on-cash for Class B beginning in Year 2. $20,800 annual cash flow on $160,000 of equity."
    timing_only = "The operator will review liquidity after 13 months."
    async with async_session() as db:
        doc = DealDocument(deal_id=deal, filename="offering.pdf", file_path="scope-offering.pdf",
                           file_sha256="d" * 64, page_count=1, extracted_text=f"--- Page 1 ---\n{quote}\n{timing_only}")
        db.add(doc)
        await db.commit()
        doc_id = doc.id

    start = (await client.get(url)).json()
    resolution = await client.post(f"{url}/analysis/resolve", json={
        "expected_revision": start["revision"], "reason": "Underwriting packet review.",
        "fields": [{"path": "target_returns.primary_strategy", "value": "hold"}, {"path": path, "value": 13}],
    })
    assert resolution.status_code == 200, resolution.text
    legacy = (await client.get(url)).json()
    assert legacy["target_cash_on_cash"] == 13
    data = {"expected_revision": legacy["revision"], "path": path, "action": "scope", "scenario": "hold",
            "investor_class": "Class B", "basis": "Annual cash flow / invested equity", "period": "Annual, beginning in Year 2",
            "source_doc_id": doc_id, "source_page": 1, "source_excerpt": quote}
    endpoint = f"{url}/analysis/return-context"
    assert (await client.put(endpoint, json={**data, "source_excerpt": timing_only})).status_code == 422
    saved = await client.put(endpoint, json=data)
    assert saved.status_code == 200, saved.text
    assert (await client.put(endpoint, json=data)).status_code == 409
    scoped = saved.json()["analysis"]["facts"][path]
    assert scoped["value"] == 13 and scoped["state"] == "manual" and scoped["locked"]
    assert scoped["identity"]["investor_class"] == "Class B"
    assert scoped["evidence"][0]["document_id"] == doc_id

    ids = {"deal_ids": [deal, comparison]}
    compared = (await client.post("/api/deals/compare", json=ids)).json()["deals"][0]
    assert compared["analysis"]["facts"][path] == scoped
    xlsx = await client.post("/api/deals/compare/export", json=ids)
    rows = {row[0]: row for row in openpyxl.load_workbook(io.BytesIO(xlsx.content)).active.values if row[0]}
    assert data["basis"] in rows["Cash-on-Cash Context"][1]
    assert "offering.pdf, p. 1" in rows["Cash-on-Cash Evidence"][1]
    pdf = await client.get(f"/api/reports/deal/{deal}/pdf")
    with fitz.open(stream=pdf.content, filetype="pdf") as document:
        text = " ".join(" ".join(page.get_text().split()) for page in document)
    assert data["period"] in text and "offering.pdf, p. 1" in text

    async with async_session() as db:
        doc = await db.get(DealDocument, doc_id)
        doc.source_role = "alternative"
        await db.commit()
    stale = (await client.get(url)).json()
    assert stale["analysis"]["facts"][path]["identity"]["investor_class"] == "unspecified"

    held = await client.put(endpoint, json={"expected_revision": stale["revision"], "path": path,
                                          "action": "withhold", "reason": "The active source does not establish this return."})
    assert held.status_code == 200, held.text
    reviewed = held.json()["analysis"]
    assert reviewed["returns"]["cash_on_cash"] is None
    assert reviewed["facts"][path]["state"] == "disputed"
    assert reviewed["facts"][path]["value"] == 13 and reviewed["facts"][path]["locked"]
    assert (await client.get(url)).json()["metrics"]["target_returns"]["hold_scenario"]["cash_on_cash_return"] == 13


async def test_document_csv_upload_read_reprocess_and_delete(client):
    deal = await new_deal(client, "Document journey")
    uploaded = await client.post(f"/api/deals/{deal}/documents/upload",
        files={"file": ("facts.csv", b"Metric,Value\nUnits,120\nEquity,2000000\n", "text/csv")})
    assert uploaded.status_code == 200
    doc_id = uploaded.json()["id"]
    docs = await client.get(f"/api/deals/{deal}/documents")
    assert docs.status_code == 200
    assert any(d["id"] == doc_id for d in docs.json())
    file = await client.get(f"/api/deals/documents/{doc_id}/file")
    assert file.status_code == 200 and b"Units,120" in file.content
    assert file.headers["x-frame-options"] == "SAMEORIGIN"
    assert file.headers["content-security-policy"] == "frame-ancestors 'self'"
    # Ordinary application responses still cannot be framed.
    assert docs.headers["x-frame-options"] == "DENY"
    reprocessed = await client.post(f"/api/deals/documents/{doc_id}/reprocess")
    assert reprocessed.status_code == 200
    assert reprocessed.json()["text_length_after"] > 0
    assert (await client.delete(f"/api/deals/documents/{doc_id}")).status_code == 200
    assert (await client.get(f"/api/deals/documents/{doc_id}/file")).status_code == 404


@pytest.mark.parametrize("quality,text,pages", [
    ({"status": "error"}, "Error extracting text: synthetic failure", 0),
    ({"status": "extracted"}, " \n ", 1),
    ({"status": "extracted"}, "[Failed to open PDF: synthetic failure]", 0),
])
async def test_document_reprocess_preserves_reading_when_extraction_fails(client, monkeypatch, quality, text, pages):
    import copy

    from app.database import async_session
    from app.models import DealDocument
    from app.routers import deal_uploads

    deal = await new_deal(client, "Preserve source reading")
    uploaded = await client.post(f"/api/deals/{deal}/documents/upload", files={
        "file": ("facts.csv", b"Metric,Value\nUnits,120\n", "text/csv"),
    })
    assert uploaded.status_code == 200, uploaded.text
    doc_id = uploaded.json()["id"]
    fields = ("extracted_text", "page_count", "file_sha256", "content_fingerprint", "extraction_quality")
    async with async_session() as db:
        doc = await db.get(DealDocument, doc_id)
        before = {field: copy.deepcopy(getattr(doc, field)) for field in fields}
    monkeypatch.setattr(deal_uploads, "_extract_uploaded_file", lambda *args: ({}, quality, text, pages))
    response = await client.post(f"/api/deals/documents/{doc_id}/reprocess")
    assert response.status_code == 422, response.text
    assert "previous reading was preserved" in response.json()["detail"]
    async with async_session() as db:
        doc = await db.get(DealDocument, doc_id)
        assert {field: getattr(doc, field) for field in fields} == before


@pytest.mark.parametrize("status", ["queued", "running"])
async def test_document_reprocess_waits_for_active_review(client, monkeypatch, status):
    from app.database import async_session
    from app.models import ReviewJob
    from app.routers import deal_uploads
    from app.services.review_jobs import enqueue_review

    deal = await new_deal(client, "Active source review")
    uploaded = await client.post(f"/api/deals/{deal}/documents/upload", files={
        "file": ("facts.csv", b"Metric,Value\nUnits,120\n", "text/csv"),
    })
    assert uploaded.status_code == 200, uploaded.text
    doc_id = uploaded.json()["id"]
    async with async_session() as db:
        await enqueue_review(db, deal)
        job = await db.get(ReviewJob, deal)
        job.status = status
        await db.commit()
    def should_not_read(*args):
        raise AssertionError("An active review must finish before another document read starts.")
    monkeypatch.setattr(deal_uploads, "_extract_uploaded_file", should_not_read)
    response = await client.post(f"/api/deals/documents/{doc_id}/reprocess")
    assert response.status_code == 409, response.text
    assert "review to finish" in response.json()["detail"]


async def test_portfolio_exports_and_chat_history(client):
    deal = await new_deal(client, "Export coverage")
    investment = await client.post("/api/investments/", json={
        "project_name": "Export coverage", "amount_invested": 10000,
        "investment_date": "2025-01-01", "deal_id": deal,
    })
    assert investment.status_code == 200
    inv_id = investment.json()["id"]
    distribution = await client.post(f"/api/investments/{inv_id}/distributions",
        json={"date": "2025-12-31", "amount": 500})
    assert distribution.status_code == 200
    for path in ["/api/investments/portfolio", "/api/investments/portfolio/analytics",
                 f"/api/investments/{inv_id}/performance", "/api/deals/pipeline/summary",
                 f"/api/chat/history/{deal}"]:
        response = await client.get(path)
        assert response.status_code == 200, (path, response.text)
    assert (await client.delete(f"/api/chat/history/{deal}")).status_code == 200
    workbook = await client.get("/api/reports/portfolio/excel")
    assert workbook.status_code == 200
    assert openpyxl.load_workbook(io.BytesIO(workbook.content)).sheetnames
    pdf = await client.get("/api/reports/portfolio/quarterly/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    exported = await client.get("/api/reports/export/json")
    assert exported.status_code == 200
    assert exported.json()
    csv = await client.get("/api/reports/export/csv")
    assert csv.status_code == 200
    assert zipfile.ZipFile(io.BytesIO(csv.content)).namelist()


async def test_linked_investment_loads_sponsor_and_uses_accepted_returns(client):
    developer = (await client.post("/api/developers", json={"name": "Synthetic Sponsor"})).json()["id"]
    deal = (await client.post("/api/deals", json={"project_name": "Linked", "developer_id": developer})).json()["id"]
    await client.put(f"/api/deals/{deal}", json={"metrics": {
        "target_returns": {"primary_strategy": "hold", "target_irr": 20,
            "sale_scenario": {"sale_irr": 20, "sale_equity_multiple": 2, "is_hypothetical": True},
            "hold_scenario": {"cash_on_cash_return": 8}},
    }})
    response = await client.post("/api/investments/", json={"deal_id": deal, "amount_invested": 1000})
    assert response.status_code == 200, response.text
    position = (await client.get(f"/api/investments/{response.json()['id']}")).json()
    assert position["sponsor_name"] == "Synthetic Sponsor"
    assert position["projected_irr"] is None
    assert position["projected_equity_multiple"] is None


async def test_nested_field_edit_updates_actual_value_and_preserves_lock(client):
    deal = await new_deal(client, "Nested values")
    path = "target_returns.hold_scenario.cash_on_cash_return"
    response = await client.post(f"/api/deals/{deal}/fields/edit", json={"path": path, "value": 8, "lock": True})
    assert response.status_code == 200
    metrics = (await client.get(f"/api/deals/{deal}")).json()["metrics"]
    assert metrics["target_returns"]["hold_scenario"]["cash_on_cash_return"] == 8
    assert metrics["_locks"][path] is True


async def test_chat_persists_current_reviewed_facts_without_provider(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    deal = await new_deal(client, "Current chat evidence")
    await client.post(f"/api/deals/{deal}/fields/edit", json={"path": "deal_structure.minimum_investment", "value": 25000, "lock": True})
    response = await client.post("/api/chat", json={"deal_id": deal, "message": "What are the investment terms?"})
    assert response.status_code == 200
    assert "25,000" in response.json()["response"]
    assert "analyst-resolved" in response.json()["response"]
    history = (await client.get(f"/api/chat/history/{deal}")).json()
    assert history[-1]["content"] == response.json()["response"]
    assert history[-1]["stale"] is False
    assert history[-1]["references"][0]["path"] == "deal_structure.minimum_investment"
