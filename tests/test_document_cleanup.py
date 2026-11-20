from pathlib import Path

import pytest


pytestmark = pytest.mark.asyncio


async def _create_upload(client):
    created = await client.post("/api/deals", json={"project_name": "Synthetic retention fixture"})
    deal_id = created.json()["id"]
    uploaded = await client.post(f"/api/deals/{deal_id}/documents/upload", files={
        "file": ("synthetic.csv", b"Term,Value\nMinimum investment,40000\n", "text/csv"),
    })
    assert uploaded.status_code == 200
    document_id = uploaded.json()["id"]
    from app.database import async_session
    from app.models import DealDocument

    async with async_session() as db:
        doc = await db.get(DealDocument, document_id)
        return deal_id, document_id, Path(doc.file_path)


async def test_purge_clears_original_only_after_permanent_deletion(client):
    deal_id, _, original = await _create_upload(client)
    assert original.is_file()
    assert (await client.delete(f"/api/deals/{deal_id}")).status_code == 200
    assert original.is_file()
    purged = await client.delete(f"/api/deals/{deal_id}/purge")
    assert purged.status_code == 200
    assert purged.json()["cleanup_pending"] is False
    assert not original.exists()


async def test_pending_cleanup_survives_a_temporary_file_error(client, monkeypatch):
    _, document_id, original = await _create_upload(client)
    unlink = Path.unlink

    def busy(path, *args, **kwargs):
        if path == original:
            raise OSError("Synthetic file is in use")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(Path, "unlink", busy)
        deleted = await client.delete(f"/api/deals/documents/{document_id}")
        assert deleted.status_code == 200
        assert deleted.json()["cleanup_pending"] is True
        assert original.is_file()
    assert (await client.get(f"/api/deals/documents/{document_id}/file")).status_code == 404

    from app.database import async_session
    from app.models import DocumentFileCleanup
    from app.services.document_cleanup import drain_document_cleanup

    async with async_session() as db:
        assert await db.get(DocumentFileCleanup, original.name) is not None
    assert await drain_document_cleanup(original.parent, [original.name])
    assert not original.exists()


async def test_shared_original_is_retained_until_the_last_record_is_deleted(client):
    deal_id, document_id, original = await _create_upload(client)
    second = (await client.post("/api/deals", json={"project_name": "Synthetic second owner"})).json()["id"]

    from app.database import async_session
    from app.models import DealDocument

    async with async_session() as db:
        copy = DealDocument(deal_id=second, filename="same-source.csv", file_path=str(original), doc_type="other")
        db.add(copy)
        await db.commit()
        second_document_id = copy.id
    assert (await client.delete(f"/api/deals/{deal_id}")).status_code == 200
    assert (await client.delete(f"/api/deals/{deal_id}/purge")).status_code == 200
    assert original.is_file()
    assert (await client.get(f"/api/deals/documents/{document_id}/file")).status_code == 404
    assert (await client.get(f"/api/deals/documents/{second_document_id}/file")).status_code == 200
    assert (await client.delete(f"/api/deals/documents/{second_document_id}")).status_code == 200
    assert not original.exists()


async def test_purge_preserves_linked_investment_and_original(client):
    deal_id, _, original = await _create_upload(client)
    linked = await client.post("/api/investments/", json={
        "deal_id": deal_id, "project_name": "Synthetic retention fixture",
        "investment_date": "2025-07-01", "amount_invested": 40000,
    })
    assert linked.status_code == 200
    assert (await client.delete(f"/api/deals/{deal_id}")).status_code == 200
    purged = await client.delete(f"/api/deals/{deal_id}/purge")
    assert purged.status_code == 409
    assert original.is_file()
    assert (await client.get(f"/api/investments/{linked.json()['id']}")).status_code == 200
