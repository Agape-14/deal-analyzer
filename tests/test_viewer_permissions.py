"""Route-level permission tests with real session logins and synthetic data."""

import pytest


@pytest.mark.asyncio
async def test_viewer_keeps_document_access_and_analyst_tools_require_operator(client, monkeypatch):
    from app.auth import hash_password
    from app.services.operation_log import record

    monkeypatch.setenv("AUTH_DISABLED", "0")
    monkeypatch.setenv("AUTH_USERNAME", "synthetic-admin")
    monkeypatch.setenv("AUTH_PASSWORD_HASH", hash_password("synthetic-admin-password"))
    monkeypatch.setenv("VIEWER_USERNAME", "synthetic-viewer")
    monkeypatch.setenv("VIEWER_PASSWORD_HASH", hash_password("synthetic-viewer-password"))

    admin = await client.post("/api/auth/login", json={
        "username": "synthetic-admin", "password": "synthetic-admin-password",
    })
    assert admin.status_code == 200
    assert admin.json()["role"] == "admin"

    created = await client.post("/api/deals", json={"project_name": "Synthetic permissions"})
    assert created.status_code == 200
    deal_id = created.json()["id"]
    deal = f"/api/deals/{deal_id}"
    upload = await client.post(f"{deal}/documents/upload", files={
        "file": ("terms.csv", b"Metric,Value\nManagement fee,1%\n", "text/csv"),
    })
    assert upload.status_code == 200
    doc_id = upload.json()["id"]

    packet = await client.get(f"{deal}/review/packet")
    assert packet.status_code == 200
    assert packet.json()["packet"]["sources"][0]["id"] == doc_id
    draft = await client.post(f"{deal}/review/draft", json={
        "package_id": packet.json()["packet"]["package_id"], "facts": [],
    })
    assert draft.status_code == 200
    assert draft.json()["draft"]["provider"] == "codex"
    reply = await client.post("/api/chat", json={"deal_id": deal_id, "message": "What fees apply?"})
    assert reply.status_code == 200

    async with record("synthetic-permissions-check") as operation:
        operation.prompt_preview = "Synthetic diagnostics preview"

    analyst_reads = [
        "/api/admin/diagnostics",
        "/api/admin/diagnostics?full=1",
        "/api/admin/ai-usage",
        "/api/reports/export/json",
        "/api/reports/export/csv",
        f"{deal}/review/packet",
        f"{deal}/review/draft",
        f"{deal}/analysis/preview",
        f"{deal}/quality",
        f"/api/chat/history/{deal_id}",
    ]
    for path in analyst_reads:
        assert (await client.get(path)).status_code == 200, path
    diagnostics = await client.get("/api/admin/diagnostics?full=1")
    assert diagnostics.json()["entries"][0]["prompt_preview"] == "Synthetic diagnostics preview"
    history = await client.get(f"/api/chat/history/{deal_id}")
    assert [message["role"] for message in history.json()] == ["user", "assistant"]

    logout = await client.post("/api/auth/logout")
    assert logout.status_code == 200
    for path in analyst_reads:
        assert (await client.get(path)).status_code == 401, path

    viewer = await client.post("/api/auth/login", json={
        "username": "synthetic-viewer", "password": "synthetic-viewer-password",
    })
    assert viewer.status_code == 200
    assert viewer.json()["role"] == "viewer"
    for path in analyst_reads:
        assert (await client.get(path)).status_code == 403, path

    assert (await client.get(deal)).status_code == 200
    assert (await client.get(f"{deal}/analysis/history")).status_code == 200
    documents = await client.get(f"{deal}/documents")
    assert documents.status_code == 200
    assert [document["id"] for document in documents.json()] == [doc_id]
    original = await client.get(f"/api/deals/documents/{doc_id}/file")
    assert original.status_code == 200
    search = await client.get("/api/chat/search", params={"q": "fees", "deal_id": deal_id})
    assert search.status_code == 200
    assert search.json()["hits"][0]["document_id"] == doc_id
    report = await client.get(f"/api/reports/deal/{deal_id}/pdf")
    assert report.status_code == 200 and report.content.startswith(b"%PDF")
    workbook = await client.get("/api/reports/portfolio/excel")
    assert workbook.status_code == 200 and workbook.content.startswith(b"PK")
