from types import SimpleNamespace
import pytest

from app.services.document_versions import document_inventory, review_documents
from app.services.analysis import evidence_for


def doc(id, digest, role="active", name="Memo.pdf"):
    return SimpleNamespace(id=id, filename=name, file_sha256=digest, source_role=role,
        extracted_text="Some usable text", extraction_quality={})


def test_duplicate_identity_requires_equal_bytes_not_equal_names_or_text():
    docs = [doc(1, "a"), doc(2, "a"), doc(3, "b"), doc(4, "")]
    inventory = document_inventory(docs)
    assert inventory[2]["duplicate_of_id"] == 1
    assert inventory[3]["same_name_different_content"]
    assert [d.id for d in review_documents(docs)] == [1, 3, 4]
    assert inventory[4]["duplicate_of_id"] is None


def test_review_excludes_replaced_and_alternate_sources_but_preserves_originals():
    docs = [doc(1, "a", "superseded"), doc(2, "a"), doc(3, "b", "alternative")]
    assert [d.id for d in review_documents(docs)] == [2]
    assert len(docs) == 3


def test_failed_legacy_duplicate_does_not_hide_successful_copy():
    docs = [doc(1, "a"), doc(2, "a")]
    docs[0].extraction_quality = {"status": "error"}
    assert [d.id for d in review_documents(docs)] == [2]


def test_exact_citation_identity_and_hash_deduplication():
    docs = [{"id": n, "filename": "Memo.pdf", "file_sha256": digest,
             "content_hash": digest, "page_count": 3} for n, digest in [(1, "a"), (2, "a")]]
    proof = {"source_doc_id": 2, "source_doc_name": "Memo.pdf", "source_page": 1}
    assert evidence_for(proof, docs)[0][0]["document_id"] == 2
    del proof["source_doc_id"]
    assert evidence_for(proof, docs)[1] == ""
    docs[1]["file_sha256"] = "b"
    assert "ambiguous" in evidence_for(proof, docs)[1]
    proof["source_doc_id"] = 1
    docs[0]["source_role"] = "superseded"
    assert "superseded" in evidence_for(proof, docs)[1]


@pytest.mark.asyncio
async def test_duplicate_upload_does_not_create_another_file_or_review(client):
    from app.database import async_session
    from app.models import ReviewJob
    from sqlalchemy import select
    deal = (await client.post("/api/deals", json={"project_name": "Version test"})).json()["id"]
    body = b"Metric,Value\nUnits,12\n"
    a = (await client.post(f"/api/deals/{deal}/documents/upload", files={"file": ("facts.csv", body, "text/csv")})).json()
    b = (await client.post(f"/api/deals/{deal}/documents/upload", files={"file": ("renamed.csv", body, "text/csv")})).json()
    assert a["id"] == b["id"] and b["duplicate"] is True
    assert len((await client.get(f"/api/deals/{deal}/documents")).json()) == 1
    async with async_session() as session:
        assert (await session.execute(select(ReviewJob))).scalars().all() == []


@pytest.mark.asyncio
async def test_explicit_version_choice_is_revision_checked_and_preserves_locks(client):
    from app.database import async_session
    from app.models import DealDocument
    from sqlalchemy import select
    deal = (await client.post("/api/deals", json={"project_name": "Version choices"})).json()["id"]
    ids = []
    for value in [10, 11]:
        upload = await client.post(f"/api/deals/{deal}/documents/upload", files={"file": ("same.csv", f"Metric,Value\nUnits,{value}\n".encode(), "text/csv")})
        ids.append(upload.json()["id"])
    await client.post(f"/api/deals/{deal}/fields/edit", json={"path": "project_details.unit_count", "value": 10, "lock": True})
    detail = (await client.get(f"/api/deals/{deal}")).json()
    assert detail["documents"][0]["same_name_different_content"]
    url = f"/api/deals/{deal}/documents/{ids[0]}/version"
    choice = {"expected_revision": detail["revision"], "source_role": "superseded", "superseded_by_id": ids[1], "reason": "Replaces the full earlier offering"}
    changed = await client.put(url, json=choice)
    assert changed.status_code == 200, changed.text
    assert (await client.put(url, json=choice)).status_code == 409
    detail = (await client.get(f"/api/deals/{deal}")).json()
    assert detail["metrics"]["_locks"]["project_details.unit_count"]
    assert detail["metrics"]["project_details"]["unit_count"] == 10
    assert len(detail["metrics"]["_document_version_history"]) == 1
    assert (await client.get(f"/api/deals/documents/{ids[0]}/file")).status_code == 200
    async with async_session() as session:
        assert len((await session.execute(select(DealDocument))).scalars().all()) == 2
    choice.update(expected_revision=detail["revision"], source_role="active", superseded_by_id=None, reason="Earlier source applies again")
    assert (await client.put(url, json=choice)).status_code == 200


@pytest.mark.asyncio
async def test_replacement_cannot_reference_another_deal(client):
    deals = [(await client.post("/api/deals", json={"project_name": name})).json()["id"] for name in ("A", "B")]
    ids = []
    for deal in deals:
        ids.append((await client.post(f"/api/deals/{deal}/documents/upload", files={"file": ("x.csv", b"a,b\n1,2", "text/csv")})).json()["id"])
    detail = (await client.get(f"/api/deals/{deals[0]}")).json()
    response = await client.put(f"/api/deals/{deals[0]}/documents/{ids[0]}/version", json={"expected_revision": detail["revision"], "source_role": "superseded", "superseded_by_id": ids[1], "reason": "Cross deal reference"})
    assert response.status_code == 422
