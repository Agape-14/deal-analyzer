"""A sourced year series can complete a hold review without inventing a headline."""
import pytest

pytestmark = pytest.mark.asyncio

QUOTES = [
    "Year-1 cash-on-cash 0.0%",
    "Year-2 cash-on-cash 12.5%",
    "Year-3 cash-on-cash n/a",
]


async def seed_hold(client):
    from app.database import async_session
    from app.models import DealDocument

    created = await client.post("/api/deals", json={"project_name": "Synthetic hold schedule"})
    assert created.status_code == 200, created.text
    deal_id = created.json()["id"]
    url = f"/api/deals/{deal_id}"
    deal = (await client.get(url)).json()
    saved = await client.post(f"{url}/analysis/resolve", json={
        "expected_revision": deal["revision"], "reason": "Synthetic underwriting terms.",
        "fields": [
            {"path": "target_returns.primary_strategy", "value": "hold"},
            {"path": "deal_structure.minimum_investment", "value": 100000},
            {"path": "deal_structure.total_equity_required", "value": 800000},
            {"path": "deal_structure.total_project_cost", "value": 2000000},
            {"path": "deal_structure.debt_amount", "value": 1200000},
            {"path": "project_details.unit_count", "value": 20},
        ],
    })
    assert saved.status_code == 200, saved.text
    async with async_session() as db:
        doc = DealDocument(deal_id=deal_id, filename="forecast.pdf", file_path="synthetic-forecast.pdf",
                           file_sha256="f" * 64, page_count=1, extracted_text="--- Page 1 ---\n" + "\n".join(QUOTES))
        db.add(doc)
        await db.commit()
        doc_id = doc.id
    deal = (await client.get(url)).json()
    payload = {
        "expected_revision": deal["revision"], "source_doc_id": doc_id, "source_page": 1,
        "investor_class": "Class B", "equity_basis": "Prior-year remaining equity",
        "period_basis": "Years after stabilization", "assumptions": "Year 3 follows full redemption.",
        "rows": [{"year": i, "cash_on_cash_pct": value, "source_excerpt": quote,
                  "note": "Source marks the return unavailable after redemption." if value is None else ""}
                 for i, (value, quote) in enumerate(zip((0, 12.5, None), QUOTES), start=1)],
    }
    return url, deal, payload


async def test_cited_schedule_completes_hold_review_and_stales_when_active_sources_change(client):
    from app.database import async_session
    from app.models import DealDocument

    url, deal, payload = await seed_hold(client)
    assert [q["area"] for q in deal["analysis"]["questions"]] == ["Returns"]

    saved = await client.put(f"{url}/analysis/return-schedule", json=payload)
    assert saved.status_code == 200, saved.text
    snapshot = (await client.get(url)).json()["analysis"]
    assert snapshot["version"] > deal["analysis"]["version"]
    assert snapshot["questions"] == []
    assert snapshot["returns"]["cash_on_cash"] is None
    schedule = snapshot["return_schedule"]
    assert [row["cash_on_cash_pct"] for row in schedule["rows"]] == [0, 12.5, None]
    assert schedule["equity_basis"] == "Prior-year remaining equity"
    assert schedule["evidence"][0]["page"] == 1
    assert schedule["evidence"][0]["content_hash"] == "f" * 64

    # A second submission with the original revision may not replace the result.
    assert (await client.put(f"{url}/analysis/return-schedule", json=payload)).status_code == 409
    async with async_session() as db:
        doc = await db.get(DealDocument, payload["source_doc_id"])
        doc.source_role = "alternative"
        await db.commit()
    stale = (await client.get(url)).json()["analysis"]
    assert stale["return_schedule"] is None
    assert [q["area"] for q in stale["questions"]] == ["Returns"]
    history = (await client.get(f"{url}/analysis/{snapshot['version']}")).json()
    assert history["return_schedule"] == schedule


async def test_schedule_supersedes_scalar_yield_without_discarding_its_history(client):
    url, deal, payload = await seed_hold(client)
    path = "target_returns.hold_scenario.cash_on_cash_return"
    resolved = await client.post(f"{url}/analysis/resolve", json={
        "expected_revision": deal["revision"], "reason": "Synthetic prior analyst decision.",
        "fields": [{"path": path, "value": 99}],
    })
    assert resolved.status_code == 200, resolved.text
    before = (await client.get(url)).json()
    assert before["analysis"]["returns"]["cash_on_cash"] == 99
    payload["expected_revision"] = before["revision"]

    saved = await client.put(f"{url}/analysis/return-schedule", json=payload)
    assert saved.status_code == 200, saved.text
    snapshot = (await client.get(url)).json()["analysis"]
    assert snapshot["returns"]["cash_on_cash"] is None
    assert snapshot["accepted_metrics"]["target_returns"]["hold_scenario"]["cash_on_cash_return"] is None
    assert snapshot["facts"][path]["value"] == 99


async def test_schedule_rejects_wrong_year_uncited_number_and_undocumented_unavailable_value(client):
    import copy

    url, _, payload = await seed_hold(client)
    route = f"{url}/analysis/return-schedule"
    cases = [
        (0, {"source_excerpt": QUOTES[1]}),
        (1, {"cash_on_cash_pct": 2}),
        (1, {"source_excerpt": "Year-2 cash-on-cash 15.5%", "cash_on_cash_pct": 15.5}),
        (2, {"note": ""}),
    ]
    for index, edits in cases:
        invalid = copy.deepcopy(payload)
        invalid["rows"][index].update(edits)
        rejected = await client.put(route, json=invalid)
        assert rejected.status_code == 422, rejected.text
    assert (await client.get(url)).json()["analysis"]["return_schedule"] is None


async def test_workbook_schedule_checks_the_value_cell_instead_of_neighboring_data(client):
    url, _, _ = await seed_hold(client)
    upload = await client.post(f"{url}/documents/upload", files={
        "file": ("forecast.csv", b"Period,Cash-on-cash,Unrelated\nYear 1,0.125,0.415\nYear 2,0.158,0.515\n", "text/csv"),
    })
    assert upload.status_code == 200, upload.text
    packet = (await client.get(f"{url}/review/packet")).json()["packet"]
    source = next(d for d in packet["sources"] if d["filename"] == "forecast.csv")
    marker = next(line for line in source["text"].splitlines() if line.startswith("--- Sheet: "))
    sheet = marker.removeprefix("--- Sheet: ").removesuffix(" ---")
    quote = next(line for line in source["text"].splitlines() if "B2=" in line)
    current = (await client.get(url)).json()
    payload = {
        "expected_revision": current["revision"], "source_doc_id": source["id"], "source_sheet": sheet,
        "investor_class": "Class B", "equity_basis": "Equity invested", "period_basis": "After stabilization",
        "rows": [{"year": 1, "cash_on_cash_pct": 41.5, "source_cell": "B2", "source_excerpt": quote}],
    }
    route = f"{url}/analysis/return-schedule"
    rejected = await client.put(route, json=payload)
    assert rejected.status_code == 422, rejected.text
    payload["rows"][0]["cash_on_cash_pct"] = 12.5
    saved = await client.put(route, json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["analysis"]["return_schedule"]["rows"][0]["cash_on_cash_pct"] == 12.5

    import io
    import fitz
    import openpyxl

    payload["expected_revision"] = saved.json()["revision"]
    payload["rows"].append({
        "year": 2, "cash_on_cash_pct": 15.8, "source_cell": "B3",
        "source_excerpt": next(line for line in source["text"].splitlines() if "B3=" in line),
    })
    updated = await client.put(route, json=payload)
    assert updated.status_code == 200, updated.text
    second_deal = await client.post("/api/deals", json={"project_name": "Second fixture"})
    deal_id = int(url.rsplit("/", 1)[1])
    comparison = await client.post("/api/deals/compare/export", json={"deal_ids": [deal_id, second_deal.json()["id"]]})
    assert comparison.status_code == 200
    sheet = openpyxl.load_workbook(io.BytesIO(comparison.content))["Return Projections"]
    rows = list(sheet.values)[1:]
    assert [(row[1], row[2]) for row in rows] == [(1, 12.5), (2, 15.8)]
    assert rows[0][-1].endswith(" B2")
    assert rows[1][-1].endswith(" B3")
    report = await client.get(f"/api/reports/deal/{deal_id}/pdf")
    assert report.status_code == 200
    with fitz.open(stream=report.content, filetype="pdf") as pdf:
        text = "\n".join(page.get_text() for page in pdf)
    assert "Cell B2" in text and "Cell B3" in text
