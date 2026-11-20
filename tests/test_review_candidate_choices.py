import re

import pytest


pytestmark = pytest.mark.asyncio
PATH = "deal_structure.minimum_investment"
UNIT_PATH = "project_details.unit_count"


async def _upload(client, deal_id, number, value):
    response = await client.post(
        f"/api/deals/{deal_id}/documents/upload",
        files={"file": (f"terms-{number}.csv", f"Term,Value,Units\nMinimum Investment,{value},125\n".encode(), "text/csv")},
    )
    assert response.status_code == 200, response.text


async def _deal_and_sources(client):
    created = await client.post("/api/deals", json={"project_name": "Synthetic source options"})
    assert created.status_code == 200, created.text
    deal_id = created.json()["id"]
    await _upload(client, deal_id, 1, 500000)
    await _upload(client, deal_id, 2, 650000)
    return deal_id


def _fact(source, value, **changes):
    text = source["text"]
    return {
        "path": PATH, "value": value, "currency": "USD", "source_doc_id": source["id"],
        "source_sheet": re.search(r"^--- Sheet: (.+) ---$", text, re.M)[1], "source_cell": "B2",
        "source_excerpt": next(line for line in text.splitlines() if "B2=" in line),
    } | changes


async def _draft(client, deal_id, *, second=None, include_units=False):
    base = f"/api/deals/{deal_id}/review"
    packet_response = await client.get(base + "/packet")
    assert packet_response.status_code == 200, packet_response.text
    packet = packet_response.json()["packet"]
    sources = {doc["filename"]: doc for doc in packet["sources"]}
    first_source = sources["terms-1.csv"]
    facts = [
        _fact(first_source, 500000),
        _fact(sources["terms-2.csv"], 650000) | (second or {}),
    ]
    if include_units:
        facts.append(_fact(first_source, 125, path=UNIT_PATH, source_cell="C2", currency=None))
    response = await client.post(base + "/draft", json={"package_id": packet["package_id"], "facts": facts})
    assert response.status_code == 200, response.text
    return base, response.json()


def _approval(view, **selection):
    return {"draft_id": view["draft"]["id"], "expected_revision": view["revision"]} | selection


async def test_choose_one_cited_value_and_keep_other_options_in_audit(client):
    deal_id = await _deal_and_sources(client)
    base, view = await _draft(client, deal_id, include_units=True)
    first, second, unrelated = view["draft"]["rows"]
    assert first["candidate_id"] != second["candidate_id"]
    assert first["issue"] and second["issue"]
    assert not first["candidate_issue"] and not second["candidate_issue"]
    assert not unrelated["issue"]

    assert (await client.post(base + "/approve", json=_approval(view, paths=[PATH]))).status_code == 422
    assert (await client.post(base + "/approve", json=_approval(
        view, candidate_ids=[first["candidate_id"], second["candidate_id"]],
    ))).status_code == 422
    before = (await client.get(f"/api/deals/{deal_id}")).json()
    assert before["analysis"]["facts"][PATH]["value"] is None

    response = await client.post(base + "/approve", json=_approval(view, candidate_ids=[second["candidate_id"]]))
    assert response.status_code == 200, response.text
    assert response.json()["applied"] == 1
    remaining = response.json()["draft"]
    assert not remaining["stale"]
    assert [row["path"] for row in remaining["rows"]] == [UNIT_PATH]

    after = (await client.get(f"/api/deals/{deal_id}")).json()
    fact = after["analysis"]["facts"][PATH]
    assert fact["state"] == "checked"
    assert fact["value"] == 650000
    assert fact["evidence"][0]["document_name"] == "terms-2.csv"
    provenance = after["metrics"]["_provenance"][PATH]
    assert "conflict" not in provenance
    audit = provenance["conflict_review"]
    assert audit["selected_id"] == second["candidate_id"]
    assert [(row["value"], row["evidence"]["source_doc_name"]) for row in audit["options"]] == [
        (500000, "terms-1.csv"), (650000, "terms-2.csv"),
    ]


@pytest.mark.parametrize("second", [{"currency": "CAD"}, {"value": 740000}])
async def test_incomparable_or_unsupported_options_cannot_be_applied(client, second):
    deal_id = await _deal_and_sources(client)
    base, view = await _draft(client, deal_id, second=second)
    choices = view["draft"]["rows"]
    assert all(row["candidate_issue"] for row in choices)
    response = await client.post(base + "/approve", json=_approval(view, candidate_ids=[choices[0]["candidate_id"]]))
    assert response.status_code == 422


async def test_changed_source_package_rejects_original_choice(client):
    deal_id = await _deal_and_sources(client)
    base, view = await _draft(client, deal_id)
    choice = view["draft"]["rows"][0]["candidate_id"]
    await _upload(client, deal_id, 3, 700000)
    response = await client.post(base + "/approve", json=_approval(view, candidate_ids=[choice]))
    assert response.status_code == 409


async def test_manually_locked_value_cannot_be_replaced_by_a_choice(client):
    deal_id = await _deal_and_sources(client)
    saved = await client.post(f"/api/deals/{deal_id}/fields/edit", json={"path": PATH, "value": 500000, "lock": True})
    assert saved.status_code == 200, saved.text
    base, view = await _draft(client, deal_id)
    rows = view["draft"]["rows"]
    assert all("locked" in row["candidate_issue"] for row in rows)
    response = await client.post(base + "/approve", json=_approval(view, candidate_ids=[rows[0]["candidate_id"]]))
    assert response.status_code == 422
