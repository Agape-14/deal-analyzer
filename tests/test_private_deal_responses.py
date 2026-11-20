import csv
import io
import zipfile

import pytest
from openpyxl import load_workbook


pytestmark = pytest.mark.asyncio


async def test_documents_and_report_follow_live_deal_visibility(client):
    created = await client.post("/api/deals", json={"project_name": "Synthetic archived deal"})
    deal_id = created.json()["id"]
    upload = await client.post(
        f"/api/deals/{deal_id}/documents/upload",
        files={"file": ("synthetic.csv", b"Name,Amount\nFixture,40000\n", "text/csv")},
    )
    assert upload.status_code == 200
    document_id = upload.json()["id"]
    file_url = f"/api/deals/documents/{document_id}/file"
    text_url = f"/api/deals/documents/{document_id}/text"
    pdf_url = f"/api/reports/deal/{deal_id}/pdf"
    for path in (file_url, text_url, pdf_url):
        response = await client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"

    assert (await client.delete(f"/api/deals/{deal_id}")).status_code == 200
    for path in (file_url, text_url, pdf_url):
        assert (await client.get(path)).status_code == 404
    assert (await client.get(f"/api/deals/{deal_id}/documents")).json() == []
    export = (await client.get("/api/reports/export/json")).json()
    assert all(deal["id"] != deal_id for deal in export["deals"])

    assert (await client.post(f"/api/deals/{deal_id}/restore")).status_code == 200
    assert (await client.get(file_url)).status_code == 200


async def test_export_text_is_literal_and_numeric_columns_keep_types(client):
    created = await client.post("/api/investments", json={
        "project_name": "+ North Quarter",
        "sponsor_name": "Synthetic Sponsor",
        "amount_invested": 25000,
        "investment_date": "2025-07-01",
        "notes": "＝ operational note",
    })
    assert created.status_code == 200

    excel = await client.get("/api/reports/portfolio/excel")
    assert excel.status_code == 200
    workbook = load_workbook(io.BytesIO(excel.content))
    sheet = workbook["Investments"]
    assert sheet["B2"].value == "+ North Quarter"
    assert sheet["B2"].data_type == "s"
    assert sheet["G2"].value == 25000
    assert sheet["G2"].data_type == "n"
    assert sheet["U2"].value == "＝ operational note"
    assert sheet["U2"].data_type == "s"

    zipped = await client.get("/api/reports/export/csv")
    assert zipped.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zipped.content)) as archive:
        row = next(csv.DictReader(io.StringIO(archive.read("investments.csv").decode())))
    assert row["project_name"] == "'+ North Quarter"
    assert row["amount_invested"] == "25000.0"
    assert row["notes"] == "'＝ operational note"
