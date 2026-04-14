"""Notifications endpoints: unread count, list, mark read."""

import pytest

pytestmark = pytest.mark.asyncio


async def test_notifications_list_starts_empty(client):
    r = await client.get("/api/notifications")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["unread"] == 0


async def test_notifications_populated_by_upload(client, tmp_path):
    # Seed a deal
    r = await client.post("/api/deals", json={"project_name": "Notif Test"})
    deal_id = r.json()["id"]

    # Upload a tiny PDF (reportlab) so the upload path emits a notification
    import reportlab.pdfgen.canvas as _c

    pdf_path = tmp_path / "tiny.pdf"
    c = _c.Canvas(str(pdf_path))
    c.drawString(100, 750, "Smoke PDF")
    c.showPage()
    c.save()

    with open(pdf_path, "rb") as f:
        r = await client.post(
            f"/api/deals/{deal_id}/documents/upload",
            files={"file": ("tiny.pdf", f.read(), "application/pdf")},
        )
    assert r.status_code == 200

    r = await client.get("/api/notifications")
    body = r.json()
    assert body["unread"] == 1
    assert any("Uploaded" in n["title"] for n in body["items"])


async def test_mark_read(client, tmp_path):
    # Reuse the upload flow to create one notification
    r = await client.post("/api/deals", json={"project_name": "X"})
    deal_id = r.json()["id"]

    import reportlab.pdfgen.canvas as _c

    pdf_path = tmp_path / "a.pdf"
    c = _c.Canvas(str(pdf_path))
    c.drawString(100, 750, "X")
    c.showPage()
    c.save()
    with open(pdf_path, "rb") as f:
        await client.post(
            f"/api/deals/{deal_id}/documents/upload",
            files={"file": ("a.pdf", f.read(), "application/pdf")},
        )

    r = await client.get("/api/notifications/unread-count")
    assert r.json()["unread"] == 1

    # Mark-all-read clears it
    r = await client.post("/api/notifications/mark-read")
    assert r.status_code == 200

    r = await client.get("/api/notifications/unread-count")
    assert r.json()["unread"] == 0


async def test_mark_specific(client, tmp_path):
    r = await client.post("/api/deals", json={"project_name": "X"})
    deal_id = r.json()["id"]

    import reportlab.pdfgen.canvas as _c

    pdf_path = tmp_path / "b.pdf"
    c = _c.Canvas(str(pdf_path))
    c.drawString(100, 750, "Y")
    c.showPage()
    c.save()
    with open(pdf_path, "rb") as f:
        await client.post(
            f"/api/deals/{deal_id}/documents/upload",
            files={"file": ("b.pdf", f.read(), "application/pdf")},
        )

    r = await client.get("/api/notifications")
    items = r.json()["items"]
    assert items
    one_id = items[0]["id"]

    r = await client.post(f"/api/notifications/{one_id}/mark-read")
    assert r.status_code == 200

    r = await client.post("/api/notifications/99999/mark-read")
    assert r.status_code == 404
