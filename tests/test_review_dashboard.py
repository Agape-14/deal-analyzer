"""The deal list uses the same current readiness as the deal detail."""

import pytest
from sqlalchemy import event


@pytest.mark.asyncio
async def test_dashboard_reading_uses_current_metadata_without_loading_source_text(client):
    from app.database import async_session, engine
    from app.models import DealDocument

    deal_id = (await client.post("/api/deals", json={"project_name": "Dashboard review"})).json()["id"]
    async with async_session() as db:
        workbook = DealDocument(
            deal_id=deal_id, filename="Forecast.xlsx", file_path="synthetic-workbook.xlsx",
            file_sha256="a" * 64, page_count=1,
            extracted_text="Synthetic model: [formula has no cached value]",
            extraction_quality={"status": "extracted", "document_kind": "spreadsheet"},
        )
        duplicate = DealDocument(
            deal_id=deal_id, filename="Duplicate.xlsx", file_path="synthetic-duplicate.xlsx",
            file_sha256="a" * 64, extraction_quality={"status": "error"},
        )
        db.add_all([workbook, duplicate])
        await db.commit()
        workbook_id = workbook.id

    source_queries = []

    def capture_source_query(_conn, _cursor, sql, *_args):
        if "FROM deal_documents" in sql:
            source_queries.append(sql)

    event.listen(engine.sync_engine, "before_cursor_execute", capture_source_query)
    try:
        response = await client.get("/api/deals")
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture_source_query)

    assert response.status_code == 200, response.text
    assert len(source_queries) == 1
    assert "AS has_text" in source_queries[0] and "AS has_uncached_formulas" in source_queries[0]
    assert "deal_documents.extracted_text," not in source_queries[0].replace(
        "coalesce(deal_documents.extracted_text,", "coalesce(text,"
    )
    listed = response.json()[0]
    detail = (await client.get(f"/api/deals/{deal_id}")).json()
    assert listed["analysis"]["readiness"] == detail["analysis"]["readiness"]
    assert listed["analysis"]["review_coverage"] == detail["analysis"]["review_coverage"]
    reading = listed["analysis"]["review_coverage"]["sources"]
    assert reading["status"] == "partial"
    assert [doc["filename"] for doc in reading["documents"]] == ["Forecast.xlsx"]
    assert "no saved values" in reading["documents"][0]["issues"][0]
    assert "Synthetic model" not in response.text

    async with async_session() as db:
        workbook = await db.get(DealDocument, workbook_id)
        workbook.extracted_text = "Synthetic model: 123"
        await db.commit()

    reread = (await client.get("/api/deals")).json()[0]["analysis"]
    assert reread["review_coverage"]["sources"]["status"] == "read"
    assert next(check for check in reread["readiness"]["checks"] if check["key"] == "sources")["status"] == "checked"
