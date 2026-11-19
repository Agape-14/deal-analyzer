"""Investor records retain reviewed forecasts and reversible actual payments."""
import csv
import io
import zipfile
from datetime import date, timedelta

import openpyxl
import pytest

pytestmark = pytest.mark.asyncio


async def create_position(client, **changes):
    response = await client.post("/api/investments/", json={
        "project_name": "Synthetic ledger", "investment_date": "2024-01-01",
        "amount_invested": 1000, **changes,
    })
    assert response.status_code == 200, response.text
    return f"/api/investments/{response.json()['id']}"


async def approved_hold(client, *, schedule=True):
    from app.database import async_session
    from app.models import DealDocument

    deal_id = (await client.post("/api/deals", json={"project_name": "Synthetic approved forecast"})).json()["id"]
    url = f"/api/deals/{deal_id}"
    scalar_quote = "Class B annual cash-on-cash return 8.0% of invested equity."
    quotes = ["Year-1 cash-on-cash 0.0%", "Year-2 cash-on-cash 12.5%"]
    async with async_session() as db:
        document = DealDocument(deal_id=deal_id, filename="synthetic-forecast.pdf", file_path="synthetic-forecast.pdf",
                                file_sha256="a" * 64, page_count=1,
                                extracted_text="--- Page 1 ---\n" + "\n".join([scalar_quote, *quotes]))
        db.add(document)
        await db.commit()
        source_id = document.id
    current = (await client.get(url)).json()
    response = await client.post(f"{url}/analysis/resolve", json={
        "expected_revision": current["revision"], "reason": "Synthetic accepted investment terms.",
        "fields": [{"path": "target_returns.primary_strategy", "value": "hold"},
                   {"path": "target_returns.hold_scenario.cash_on_cash_return", "value": 8},
                   {"path": "deal_structure.hold_period_years", "value": 10}],
    })
    assert response.status_code == 200, response.text
    scoped = await client.put(f"{url}/analysis/return-context", json={
        "expected_revision": response.json()["revision"], "path": "target_returns.hold_scenario.cash_on_cash_return",
        "action": "scope", "scenario": "hold", "investor_class": "Class B", "basis": "Invested equity", "period": "Annual",
        "source_doc_id": source_id, "source_page": 1, "source_excerpt": scalar_quote,
    })
    assert scoped.status_code == 200, scoped.text
    if not schedule:
        return url, (await client.get(url)).json(), source_id
    scheduled = await client.put(f"{url}/analysis/return-schedule", json={
        "expected_revision": scoped.json()["revision"], "source_doc_id": source_id, "source_page": 1,
        "investor_class": "Class B", "equity_basis": "Remaining equity", "period_basis": "Years after stabilization", "assumptions": "",
        "rows": [{"year": index, "cash_on_cash_pct": value, "source_excerpt": quote, "note": ""}
                 for index, (value, quote) in enumerate(zip([0, 12.5], quotes), start=1)],
    })
    assert scheduled.status_code == 200, scheduled.text
    return url, (await client.get(url)).json(), source_id


async def test_linked_hold_snapshot_retains_approved_scope_sources_and_commit_after_deal_changes(client, monkeypatch):
    monkeypatch.setenv("APP_COMMIT", "a" * 40)
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    deal_url, deal, source_id = await approved_hold(client)
    position_url = await create_position(client, deal_id=deal["id"],
        expected_analysis_version=deal["analysis"]["version"], expected_analysis_input_hash=deal["analysis"]["input_hash"])
    position = (await client.get(position_url)).json()
    saved = position["forecast_snapshot"]
    assert position["projected_irr"] is position["projected_equity_multiple"] is None
    assert position["projected_cash_on_cash"] is None and position["investment_class"] == "Class B"
    assert saved["app_commit"] == "a" * 40 and saved["deal_revision"] == deal["revision"]
    assert saved["analysis_version"] == deal["analysis"]["version"]
    assert saved["analysis_input_hash"] == deal["analysis"]["input_hash"]
    evidence = saved["return_schedule"]["evidence"][0]
    assert evidence["document_id"] == source_id and evidence["content_hash"] == "a" * 64
    assert saved["return_schedule"]["investor_class"] == "Class B"
    assert saved["return_schedule"]["period_basis"] == "Years after stabilization"
    assert [row["cash_on_cash_pct"] for row in saved["return_schedule"]["rows"]] == [0, 12.5]
    changed = await client.post(f"{deal_url}/analysis/resolve", json={
        "expected_revision": deal["revision"], "reason": "New synthetic underwriting.",
        "fields": [{"path": "target_returns.hold_scenario.cash_on_cash_return", "value": 9}],
    })
    assert changed.status_code == 200, changed.text
    assert (await client.get(position_url)).json()["forecast_snapshot"] == saved
    stale_create = await client.post("/api/investments/", json={"deal_id": deal["id"], "amount_invested": 1000,
        "expected_analysis_version": saved["analysis_version"], "expected_analysis_input_hash": saved["analysis_input_hash"]})
    assert stale_create.status_code == 409


async def test_class_override_clears_inherited_returns_and_retains_baseline_and_change_history(client):
    _, deal, _ = await approved_hold(client, schedule=False)
    url = await create_position(client, deal_id=deal["id"])
    baseline = (await client.get(url)).json()["forecast_snapshot"]
    changed = await client.put(url, json={"investment_class": "Class C", "projected_cash_on_cash": 8,
        "terms_override_reason": "My subscription uses Class C."})
    assert changed.status_code == 200, changed.text
    position = (await client.get(url)).json()
    assert position["projected_cash_on_cash"] is None and position["hold_period_years"] is None
    assert position["terms_context"] is None
    assert position["forecast_snapshot"] == baseline
    assert position["terms_overrides"]["investment_class"]["baseline_value"] == "Class B"
    assert position["terms_overrides"]["investment_class"]["reason"] == "My subscription uses Class C."
    assert (await client.put(url, json={"projected_cash_on_cash": 6})).status_code == 200
    entry = (await client.get(url)).json()["terms_overrides"]["projected_cash_on_cash"]
    assert entry["value"] == 6 and entry["baseline_value"] == 8
    assert [event["value"] for event in entry["history"]] == [None, 6]


async def test_scoped_scalar_snapshot_and_explicit_same_return_for_another_class_remain_attributed(client):
    _, deal, source_id = await approved_hold(client, schedule=False)
    url = await create_position(client, deal_id=deal["id"], investment_class="")
    position = (await client.get(url)).json()
    assert position["projected_cash_on_cash"] == 8 and position["investment_class"] == "Class B"
    saved = position["forecast_snapshot"]
    fact = saved["facts"]["target_returns.hold_scenario.cash_on_cash_return"]
    assert fact["identity"]["basis"] == "Invested equity" and fact["identity"]["period"] == "Annual"
    assert fact["evidence"][0]["document_id"] == source_id
    overridden = await create_position(client, deal_id=deal["id"], projected_cash_on_cash=6)
    manual = (await client.get(overridden)).json()
    assert manual["terms_context"] is None
    assert manual["projected_cash_on_cash"] == 6
    assert manual["forecast_snapshot"]["facts"]["target_returns.hold_scenario.cash_on_cash_return"] == fact
    changed = await client.put(url, json={"investment_class": "Class C", "projected_cash_on_cash": 8, "confirmed_class_terms": True})
    assert changed.status_code == 200, changed.text
    position = (await client.get(url)).json()
    assert position["projected_cash_on_cash"] == 8
    assert position["terms_overrides"]["projected_cash_on_cash"]["investor_class"] == "Class C"
    assert position["forecast_snapshot"] == saved and position["terms_context"] is None
    other = await create_position(client, deal_id=deal["id"], investment_class="Class C", projected_cash_on_cash=8)
    assert (await client.get(other)).json()["terms_overrides"]["projected_cash_on_cash"]["investor_class"] == "Class C"


async def test_forecast_structure_terms_do_not_inherit_an_explicit_other_class_or_sale_context():
    from types import SimpleNamespace
    from app.services.investment_forecasts import accepted_forecast

    path = "target_returns.hold_scenario.cash_on_cash_return"
    analysis = {"primary_strategy": "hold", "investor_class": "unspecified", "version": 2, "input_hash": "a" * 64,
        "accepted_metrics": {"deal_structure": {"preferred_return": 7, "hold_period_years": 5}},
        "returns": {"cash_on_cash": 8, "cash_on_cash_path": path}, "facts": {
            path: {"state": "checked", "identity": {"investor_class": "Class B", "scenario": "hold"}},
            "deal_structure.preferred_return": {"state": "checked", "identity": {"investor_class": "Class A", "scenario": "hold"}},
            "deal_structure.hold_period_years": {"state": "checked", "identity": {"investor_class": "Class B", "scenario": "sale"}},
        }}
    deal = SimpleNamespace(id=1, revision=3)
    snapshot = accepted_forecast(deal, analysis)
    assert snapshot["terms"]["investment_class"] == "Class B" and snapshot["terms"]["projected_cash_on_cash"] == 8
    assert snapshot["terms"]["preferred_return"] is snapshot["terms"]["hold_period_years"] is None
    assert "deal_structure.preferred_return" in snapshot["facts"]  # Evidence remains historical, never a default.
    for field in ("preferred_return", "hold_period_years"):
        analysis["facts"]["deal_structure." + field]["identity"] = {"investor_class": "Class B", "scenario": "hold"}
    assert accepted_forecast(deal, analysis)["terms"]["preferred_return"] == 7
    for field in ("preferred_return", "hold_period_years"):
        analysis["facts"]["deal_structure." + field]["identity"] = {"investor_class": "unspecified", "scenario": "unspecified"}
    assert accepted_forecast(deal, analysis)["terms"]["hold_period_years"] == 5


async def test_manual_and_legacy_positions_work_without_inventing_approved_snapshot(client):
    url = await create_position(client, projected_cash_on_cash=7, projected_irr=14)
    position = (await client.get(url)).json()
    assert position["forecast_snapshot"] is None
    assert position["terms_overrides"]["projected_cash_on_cash"]["source"] == "manual"
    assert (await client.put(url, json={"notes": "Existing position annotation"})).status_code == 200
    for _ in range(2):
        assert (await client.post(f"{url}/distributions", json={"date": "2025-01-01", "amount": 10})).status_code == 200
    assert len((await client.get(url)).json()["distributions"]) == 2


async def test_idempotent_add_replays_after_edits_and_removal_without_duplicate_or_resurrection(client):
    url = await create_position(client)
    payload = {"date": "2025-01-01", "amount": 100, "request_id": "synthetic-payment-0001"}
    first = await client.post(f"{url}/distributions", json=payload)
    assert first.status_code == 200, first.text
    result = first.json()
    again = (await client.post(f"{url}/distributions", json=payload)).json()
    assert again["id"] == result["id"] and again["replayed"]
    assert (await client.post(f"{url}/distributions", json={**payload, "amount": 200})).status_code == 409
    item = f"{url}/distributions/{result['id']}"
    assert (await client.put(item, json={"date": "2025-02-01", "amount": 150, "expected_revision": 1})).status_code == 200
    assert (await client.delete(item + "?expected_revision=2")).status_code == 200
    replay = (await client.post(f"{url}/distributions", json=payload)).json()
    assert replay["id"] == result["id"] and replay["removed"]
    position = (await client.get(url)).json()
    assert position["distributions"] == [] and position["total_distributions"] == 0
    assert len(position["distribution_ledger"]) == 1 and position["distribution_ledger"][0]["amount"] == 150


async def test_ledger_edits_remove_restore_and_stale_mutations_are_audited_and_affect_all_exports(client):
    url = await create_position(client)
    first = (await client.post(f"{url}/distributions", json={"date": "2025-01-01", "amount": 100})).json()
    second = (await client.post(f"{url}/distributions", json={"date": "2025-02-01", "amount": 25})).json()
    item = f"{url}/distributions/{first['id']}"
    edited = await client.put(item, json={"date": "2025-01-15", "amount": 110, "notes": "Corrected payment", "expected_revision": 1})
    assert edited.status_code == 200 and edited.json()["revision"] == 2
    assert (await client.put(item, json={"date": "2025-01-01", "amount": 999, "expected_revision": 1})).status_code == 409
    assert (await client.delete(item + "?expected_revision=1")).status_code == 409
    removed = await client.delete(item + "?expected_revision=2")
    assert removed.status_code == 200 and removed.json()["revision"] == 3
    assert (await client.put(item, json={"date": "2025-01-01", "amount": 999, "expected_revision": 3})).status_code == 409
    assert (await client.post(item + "/restore", json={"expected_revision": 2})).status_code == 409
    position = (await client.get(url)).json()
    assert position["total_distributions"] == 25
    assert [d["id"] for d in position["distributions"]] == [second["id"]]
    assert (await client.get(url + "/performance")).json()["total_returned"] == 25
    assert (await client.get("/api/investments/portfolio/analytics")).json()["summary"]["total_returned"] == 25
    workbook = openpyxl.load_workbook(io.BytesIO((await client.get("/api/reports/portfolio/excel")).content))
    assert workbook["Distributions"].max_row == 2 and workbook["Distributions"].cell(2, 4).value == 25
    exported = (await client.get("/api/reports/export/json")).json()["investments"][0]
    assert len(exported["distributions"]) == 1 and len(exported["distribution_ledger"]) == 2
    with zipfile.ZipFile(io.BytesIO((await client.get("/api/reports/export/csv")).content)) as archive:
        rows = list(csv.DictReader(io.StringIO(archive.read("distributions.csv").decode())))
    assert len(rows) == 1 and float(rows[0]["amount"]) == 25
    restored = await client.post(item + "/restore", json={"expected_revision": 3})
    assert restored.status_code == 200 and restored.json()["revision"] == 4
    position = (await client.get(url)).json()
    assert position["total_distributions"] == 135
    ledger = next(row for row in position["distribution_ledger"] if row["id"] == first["id"])
    assert [entry["action"] for entry in ledger["history"]] == ["edited", "removed", "restored"]
    assert ledger["history"][0]["previous"]["amount"] == 100


@pytest.mark.parametrize("invalid", [
    {"date": "2023-12-31", "amount": 10},
    {"date": (date.today() + timedelta(days=1)).isoformat(), "amount": 10},
    {"date": "2025-01-01", "amount": -1},
    {"date": "not-a-date", "amount": 10},
])
async def test_invalid_distribution_dates_and_amounts_never_create_rows(client, invalid):
    url = await create_position(client)
    assert (await client.post(f"{url}/distributions", json=invalid)).status_code == 422
    assert (await client.get(url)).json()["distribution_ledger"] == []


async def test_archive_and_exit_chronology_guard_add_edit_restore_and_position_date_changes(client):
    url = await create_position(client)
    added = (await client.post(f"{url}/distributions", json={"date": "2025-01-01", "amount": 100})).json()
    item = f"{url}/distributions/{added['id']}"
    assert (await client.put(url, json={"investment_date": "2025-02-01"})).status_code == 422
    assert (await client.put(url, json={"status": "exited", "exit_date": "2024-12-01", "exit_amount": 1000})).status_code == 422
    assert (await client.delete(item)).status_code == 200  # Legacy delete has no revision query.
    assert (await client.put(url, json={"status": "exited", "exit_date": "2024-12-01", "exit_amount": 1000})).status_code == 200
    assert (await client.post(item + "/restore")).status_code == 422
    assert (await client.post(f"{url}/distributions", json={"date": "2025-01-01", "amount": 100})).status_code == 422
    assert (await client.delete(url)).status_code == 200
    for method, path, payload in [("post", f"{url}/distributions", {"date": "2024-06-01", "amount": 10}),
                                  ("put", item, {"date": "2024-06-01", "amount": 10}),
                                  ("post", item + "/restore", {})]:
        assert (await getattr(client, method)(path, json=payload)).status_code == 404
    assert (await client.delete(item)).status_code == 404
    assert (await client.post(url + "/restore")).status_code == 200
    assert (await client.get(url)).json()["total_distributions"] == 0


async def test_existing_schema_patch_preserves_legacy_rows_and_adds_safe_defaults(client):
    from sqlalchemy import Column, MetaData, Table, text
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.database import _apply_schema_patches
    from app.models import Investment, Distribution

    legacy = MetaData()
    new_fields = {"investments": {"forecast_snapshot", "terms_overrides", "projected_cash_on_cash"},
                  "distributions": {"deleted_at", "revision", "request_id", "request_fingerprint", "history"}}
    for model in (Investment, Distribution):
        Table(model.__tablename__, legacy, *[Column(column.name, column.type, primary_key=column.primary_key, nullable=column.nullable)
            for column in model.__table__.columns if column.name not in new_fields[model.__tablename__]])
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(legacy.create_all)
            await connection.execute(text("INSERT INTO investments (id,project_name) VALUES (1,'Legacy position')"))
            await connection.execute(text("INSERT INTO distributions (id,investment_id,date,amount) VALUES (1,1,'2025-01-01',25)"))
            await connection.run_sync(_apply_schema_patches)
            await connection.run_sync(_apply_schema_patches)
            investment = (await connection.execute(text("SELECT project_name,forecast_snapshot,terms_overrides FROM investments"))).one()
            distribution = (await connection.execute(text("SELECT amount,revision,deleted_at,request_id FROM distributions"))).one()
            indexes = (await connection.execute(text("PRAGMA index_list('distributions')"))).all()
        assert tuple(investment) == ("Legacy position", None, None)
        assert tuple(distribution) == (25, 1, None, None)
        assert any(row[1] == "uq_distributions_request" and row[2] == 1 for row in indexes)
    finally:
        await engine.dispose()
