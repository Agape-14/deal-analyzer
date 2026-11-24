import io
import re

import pytest


DEBT_PATH = "deal_structure.debt_amount"
CONSTRUCTION_LOAN_PATH = "deal_structure.construction_loan_amount"


async def upload(client, deal_id, body, name="loan.csv"):
    result = await client.post(
        f"/api/deals/{deal_id}/documents/upload",
        files={"file": (name, body.encode(), "text/csv")},
    )
    assert result.status_code == 200, result.text
    return result.json()["id"]


async def set_accepted_debt(client, deal_id, revision, amount):
    result = await client.post(
        f"/api/deals/{deal_id}/analysis/resolve",
        json={
            "expected_revision": revision,
            "reason": "Synthetic review of the project finance amount.",
            "fields": [{"path": DEBT_PATH, "value": amount}],
        },
    )
    assert result.status_code == 200, result.text
    return result.json()["revision"]


async def financing_fixture(client):
    created = await client.post("/api/deals", json={"project_name": "Synthetic loan measures"})
    assert created.status_code == 200, created.text
    deal_id = created.json()["id"]
    doc_id = await upload(
        client, deal_id, "Description,USD,Other\nDraw,500000,625000\nPeak balance,700000,\nPayoff balance,625000,\n",
    )
    deal = (await client.get(f"/api/deals/{deal_id}")).json()
    revision = await set_accepted_debt(client, deal_id, deal["revision"], 625000)
    packet_response = await client.get(f"/api/deals/{deal_id}/review/packet")
    assert packet_response.status_code == 200, packet_response.text
    source = packet_response.json()["packet"]["sources"][0]
    assert source["id"] == doc_id
    sheet = re.search(r"^--- Sheet: (.+) ---$", source["text"], re.M)[1]
    rows = []
    for kind, amount, address in (
        ("draw", 500000, "B2"),
        ("peak_balance", 700000, "B3"),
        ("modeled_payoff", 625000, "B4"),
    ):
        quote = next(line for line in source["text"].splitlines() if f"{address}=" in line)
        rows.append({
            "kind": kind, "amount": amount, "source_doc_id": doc_id,
            "source_sheet": sheet, "source_cell": address, "source_excerpt": quote,
        })
    return deal_id, revision, rows


@pytest.mark.asyncio
async def test_financing_labels_require_explicit_matching_cited_measure(client):
    deal_id, revision, rows = await financing_fixture(client)
    before = (await client.get(f"/api/deals/{deal_id}")).json()
    assert before["analysis"]["financing"]["debt_amount_label"] == "Debt amount"

    url = f"/api/deals/{deal_id}/analysis/financing-measures"
    payload = {"expected_revision": revision, "debt_amount_kind": "draw", "measures": rows}
    rejected = await client.put(url, json=payload)
    assert rejected.status_code == 422
    assert "accepted debt amount" in rejected.json()["detail"]

    payload["debt_amount_kind"] = "modeled_payoff"
    saved = await client.put(url, json=payload)
    assert saved.status_code == 200, saved.text
    deal = (await client.get(f"/api/deals/{deal_id}")).json()
    financing = deal["analysis"]["financing"]
    assert financing["debt_amount_kind"] == "modeled_payoff"
    assert financing["debt_amount_label"] == "Modeled construction debt at payoff"
    assert financing["debt_amount_currency"] == "USD"
    assert [item["amount"] for item in financing["measures"]] == [500000, 700000, 625000]
    assert all(item["state"] == "checked" for item in financing["measures"])
    assert financing["measures"][2]["evidence"][0]["cell"] == "B4"
    debt = deal["analysis"]["facts"][DEBT_PATH]
    assert debt["value"] == 625000 and debt["locked"]
    assert (await client.put(url, json=payload)).status_code == 409

    # A later analyst decision must not inherit the meaning of the old amount.
    await set_accepted_debt(client, deal_id, deal["revision"], 500000)
    updated = (await client.get(f"/api/deals/{deal_id}")).json()["analysis"]["financing"]
    assert updated["debt_amount_kind"] is None
    assert len([row for row in updated["measures"] if row["state"] == "checked"]) == 3


@pytest.mark.asyncio
async def test_financing_verifies_value_cell_and_stales_on_new_active_source(client):
    deal_id, revision, rows = await financing_fixture(client)
    url = f"/api/deals/{deal_id}/analysis/financing-measures"
    payload = {"expected_revision": revision, "debt_amount_kind": "modeled_payoff", "measures": rows}
    wrong_cell_value = {"amount": 625000}  # C2 contains this amount; cited B2 doesn't.
    rejected = await client.put(url, json={**payload, "measures": [{**rows[0], **wrong_cell_value}, *rows[1:]]})
    assert rejected.status_code == 422
    assert "supporting quote" in rejected.json()["detail"]

    rejected = await client.put(
        url, json={**payload, "measures": [{**rows[0], "kind": "lender_commitment"}, *rows[1:]]},
    )
    assert rejected.status_code == 422
    assert "identifies this measure" in rejected.json()["detail"]
    assert (await client.put(url, json=payload)).status_code == 200

    await upload(client, deal_id, "Description,USD\nDraw,300000\n", "new-loan.csv")
    analysis = (await client.get(f"/api/deals/{deal_id}")).json()["analysis"]
    financing = analysis["financing"]
    assert financing["debt_amount_kind"] is None
    assert financing["debt_amount_label"] == "Debt amount"
    assert all(row["state"] == "stale" and not row["evidence"] for row in financing["measures"])
    assert analysis["facts"][DEBT_PATH]["value"] == 625000


@pytest.mark.asyncio
async def test_pdf_financing_requires_one_measure_and_its_amount_in_each_quote(client):
    from app.database import async_session
    from app.models import DealDocument

    created = await client.post("/api/deals", json={"project_name": "Synthetic PDF loan measures"})
    assert created.status_code == 200, created.text
    deal_id = created.json()["id"]
    quotes = {
        "draw": "Construction Loan Draw\n$500,000",
        "peak_balance": "700,000 Max Loan",
        "modeled_payoff": "625,000 Construction Loan Balance @ Payoff",
    }
    other_amount = "Reserve: $125,000"
    page = "\n".join((*quotes.values(), other_amount))
    async with async_session() as db:
        doc = DealDocument(deal_id=deal_id, filename="loan.pdf", file_path="synthetic-loan.pdf",
                           file_sha256="a" * 64, page_count=1, extracted_text=f"--- Page 1 ---\n{page}")
        db.add(doc)
        await db.commit()
        doc_id = doc.id

    url = f"/api/deals/{deal_id}"
    deal = (await client.get(url)).json()
    revision = await set_accepted_debt(client, deal_id, deal["revision"], 625000)
    payload = {"expected_revision": revision, "debt_amount_kind": "modeled_payoff"}
    payoff = {"kind": "modeled_payoff", "source_doc_id": doc_id, "source_page": 1}
    for amount, quote in (
        (500000, page),
        (125000, f"{quotes['modeled_payoff']}\n{other_amount}"),
    ):
        rejected = await client.put(f"{url}/analysis/financing-measures", json={
            **payload, "debt_amount_kind": None,
            "measures": [{**payoff, "amount": amount, "source_excerpt": quote}],
        })
        assert rejected.status_code == 422, rejected.text
        assert "Quote only this financing measure" in rejected.json()["detail"]

    saved = await client.put(f"{url}/analysis/financing-measures", json={
        **payload,
        "measures": [
            {**payoff, "kind": kind, "amount": amount, "source_excerpt": quotes[kind]}
            for kind, amount in (("draw", 500000), ("peak_balance", 700000), ("modeled_payoff", 625000))
        ],
    })
    assert saved.status_code == 200, saved.text
    financing = (await client.get(url)).json()["analysis"]["financing"]
    assert financing["debt_amount_kind"] == "modeled_payoff"
    assert [measure["state"] for measure in financing["measures"]] == ["checked"] * 3


@pytest.mark.asyncio
async def test_approved_pdf_commitment_is_used_in_summary_and_exports(client):
    import fitz
    import openpyxl

    from app.database import async_session
    from app.models import Deal, DealDocument

    created = await client.post("/api/deals", json={"project_name": "Synthetic commitment"})
    deal_id = created.json()["id"]
    other = await client.post("/api/deals", json={"project_name": "Comparison"})
    quote = "Construction loan commitment: $19,800,000."
    draw_quote = "Construction loan draw: $5,000,000."
    async with async_session() as db:
        doc = DealDocument(deal_id=deal_id, filename="commitment.pdf", file_path="commitment.pdf",
                           file_sha256="d" * 64, page_count=1,
                           extracted_text=f"--- Page 1 ---\n{quote}\n{draw_quote}")
        db.add(doc)
        await db.commit()
        doc_id = doc.id

    url = f"/api/deals/{deal_id}"
    review = f"{url}/review"
    packet = (await client.get(f"{review}/packet")).json()["packet"]
    imported = await client.post(f"{review}/draft", json={"package_id": packet["package_id"], "facts": [{
        "path": CONSTRUCTION_LOAN_PATH, "value": 19_800_000, "source_doc_id": doc_id, "source_page": 1,
        "source_excerpt": quote, "basis": "Construction loan commitment", "currency": "USD", "debt_phase": "construction",
    }]})
    assert imported.status_code == 200, imported.text
    draft = imported.json()
    before = (await client.get(url)).json()["analysis"]
    assert before["financing"]["measures"] == []
    approved = await client.post(f"{review}/approve", json={
        "draft_id": draft["draft"]["id"], "expected_revision": draft["revision"], "paths": [CONSTRUCTION_LOAN_PATH],
    })
    assert approved.status_code == 200, approved.text

    # The pilot already has a saved pre-change snapshot. Reads can rebuild it
    # from the reviewed facts without another approval or deal revision.
    async with async_session() as db:
        deal = await db.get(Deal, deal_id)
        snapshot = dict(deal.analysis_snapshot)
        snapshot["schema_version"] = 7
        snapshot["financing"] = {**snapshot["financing"], "measures": []}
        deal.analysis_snapshot = snapshot
        await db.commit()

    detail = (await client.get(url)).json()
    financing = detail["analysis"]["financing"]
    assert detail["analysis"]["version"] == snapshot["version"]
    assert financing["debt_amount_label"] == "Debt amount"
    commitment, = financing["measures"]
    assert commitment["label"] == "Construction lender commitment"
    assert commitment["amount"] == 19_800_000
    assert commitment["source_path"] == CONSTRUCTION_LOAN_PATH
    assert commitment["evidence"][0]["excerpt"] == quote

    pdf = await client.get(f"/api/reports/deal/{deal_id}/pdf")
    assert pdf.status_code == 200
    with fitz.open(stream=pdf.content, filetype="pdf") as report:
        text = " ".join(" ".join(page.get_text().split()) for page in report)
    assert "Construction lender commitment · $19,800,000" in text
    assert "commitment.pdf, p. 1" in text

    xlsx = await client.post("/api/deals/compare/export", json={"deal_ids": [deal_id, other.json()["id"]]})
    assert xlsx.status_code == 200
    workbook = openpyxl.load_workbook(io.BytesIO(xlsx.content))
    assert tuple(cell.value for cell in workbook["Construction Financing"][2]) == (
        "Synthetic commitment", "Construction lender commitment", 19_800_000, "USD", None, "commitment.pdf, p. 1",
    )

    saved = await client.put(f"{url}/analysis/financing-measures", json={
        "expected_revision": detail["revision"], "measures": [{
            "kind": "draw", "amount": 5_000_000, "source_doc_id": doc_id, "source_page": 1, "source_excerpt": draw_quote,
        }],
    })
    assert saved.status_code == 200, saved.text
    explicit = (await client.get(url)).json()["analysis"]["financing"]["measures"]
    assert [measure["kind"] for measure in explicit] == ["draw"]


@pytest.mark.parametrize(("citation_change", "provenance_change", "context_change", "expected"), [
    ({}, {}, {}, True),
    ({"source_excerpt": "A5=Construction loan draw | B5=19800000 | C5=USD"}, {}, {}, False),
    ({"source_excerpt": "A5=Construction loan commitment fee | B5=19800000 | C5=USD"}, {}, {}, False),
    ({"source_excerpt": "A5=Construction loan commitment | B5=2000000 | C5=19800000"}, {}, {}, False),
    ({"source_excerpt": "A5=Construction loan commitment | B5=-19800000 | C5=USD"}, {}, {}, False),
    ({"source_document_hash": "changed"}, {}, {}, False),
    ({}, {"conflict": [19_800_000, 18_900_000]}, {}, False),
    ({}, {"status": "manual"}, {}, False),
    ({}, {"review_document_set": "stale"}, {}, False),
    ({}, {}, {"basis": "Loan amount"}, False),
    ({}, {}, {"currency": "CAD"}, False),
])
def test_commitment_requires_a_checked_unambiguous_current_workbook_source(
    citation_change, provenance_change, context_change, expected,
):
    from app.services.analysis import build_analysis, digest

    documents = [{"id": 1, "filename": "funding.xlsx", "content_hash": "current", "included_in_review": True}]
    citation = {
        "source_doc_id": 1, "source_document_hash": "current", "source_sheet": "Funding", "source_cell": "B5",
        "source_excerpt": "A5=Construction loan commitment | B5=19800000 | C5=USD",
    }
    provenance = {"status": "confirmed", "source_check_version": 1, "review_document_set": digest(documents)}
    context = {"basis": "Construction loan commitment", "currency": "USD", "debt_phase": "construction"}
    metrics = {
        "deal_structure": {"construction_loan_amount": 19_800_000},
        "_provenance": {CONSTRUCTION_LOAN_PATH: {**citation, **citation_change, **provenance, **provenance_change}},
        "_fact_context": {CONSTRUCTION_LOAN_PATH: {**context, **context_change}},
    }
    financing = build_analysis(metrics, documents)["financing"]
    assert bool(financing["measures"]) is expected
    if expected:
        assert financing["measures"][0]["evidence"][0]["cell"] == "B5"
