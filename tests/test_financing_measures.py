import re

import pytest


DEBT_PATH = "deal_structure.debt_amount"


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
