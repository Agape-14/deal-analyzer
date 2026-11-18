"""Backfills reuse production validators and keep route commits atomic."""
import importlib
import re
import sys

import pytest


pytestmark = pytest.mark.asyncio


def backfill_module():
    # Route fixtures replace the app modules and DB for each test.
    sys.modules.pop("scripts.review_backfill", None)
    return importlib.import_module("scripts.review_backfill")


async def seed_plan(client):
    created = await client.post("/api/deals", json={"project_name": "Synthetic backfill"})
    deal_id = created.json()["id"]
    uploaded = await client.post(f"/api/deals/{deal_id}/documents/upload", files={
        "file": ("terms.csv", b"Label,Value\nMinimum investment,100000\nConstruction loan draw,500000\n", "text/csv"),
    })
    assert uploaded.status_code == 200, uploaded.text
    detail = (await client.get(f"/api/deals/{deal_id}")).json()
    resolved = await client.post(f"/api/deals/{deal_id}/analysis/resolve", json={
        "expected_revision": detail["revision"], "reason": "Synthetic accepted debt amount.",
        "fields": [{"path": "deal_structure.debt_amount", "value": 500000}],
    })
    assert resolved.status_code == 200, resolved.text
    packet = (await client.get(f"/api/deals/{deal_id}/review/packet")).json()["packet"]
    source = packet["sources"][0]
    sheet = re.search(r"^--- Sheet: (.+) ---$", source["text"], re.M)[1]
    minimum = {
        "path": "deal_structure.minimum_investment", "value": 100000,
        "source_doc_id": source["id"], "source_sheet": sheet, "source_cell": "B2",
        "source_excerpt": next(line for line in source["text"].splitlines() if "B2=" in line), "currency": "USD",
    }
    unsupported = {**minimum, "path": "project_details.unit_count", "value": 7}
    detail = (await client.get(f"/api/deals/{deal_id}")).json()
    item = {
        "deal_id": deal_id, "expected_revision": detail["revision"], "package_id": packet["package_id"],
        "review": {"package_id": packet["package_id"], "facts": [minimum, unsupported]},
        "approve_paths": [minimum["path"]],
        "financing": {"debt_amount_kind": "draw", "measures": [{
            "kind": "draw", "amount": 500000, "source_doc_id": source["id"],
            "source_sheet": sheet, "source_cell": "B3",
            "source_excerpt": next(line for line in source["text"].splitlines() if "B3=" in line),
        }]},
    }
    return item, source["id"]


async def test_backfill_dry_run_apply_and_exact_replay_preserve_unselected_rows(client):
    from app.database import async_session, engine
    from app.models import Deal

    item, _ = await seed_plan(client)
    module = backfill_module()
    plan = module.BackfillPlan.model_validate({"version": 1, "deals": [item]})
    before = (await client.get(f"/api/deals/{item['deal_id']}")).json()
    preview = await module.execute_plan(plan, engine=engine)
    assert preview["status"] == "validated"
    assert preview["deals"][0]["revision"] == before["revision"]
    assert preview["deals"][0]["projected_revision"] > before["revision"]
    assert preview["deals"][0]["analysis"]["accepted_fact_count"] > 0
    assert any(row["issue"] and not row["selected"] for row in preview["deals"][0]["review"])
    after_preview = (await client.get(f"/api/deals/{item['deal_id']}")).json()
    assert after_preview["revision"] == before["revision"]
    assert after_preview["analysis"] == before["analysis"]
    assert (await client.get(f"/api/deals/{item['deal_id']}/review/draft")).json()["draft"] is None

    saved = await module.execute_plan(plan, engine=engine, apply=True)
    assert saved["status"] == "applied"
    detail = (await client.get(f"/api/deals/{item['deal_id']}")).json()
    assert detail["analysis"]["facts"]["deal_structure.minimum_investment"]["value"] == 100000
    assert detail["analysis"]["financing"]["debt_amount_kind"] == "draw"
    remaining = (await client.get(f"/api/deals/{item['deal_id']}/review/draft")).json()["draft"]
    assert not remaining["stale"]
    assert [row["path"] for row in remaining["rows"]] == ["project_details.unit_count"]
    assert remaining["rows"][0]["issue"]
    assert saved["deals"][0]["remaining_review_rows"] == 1
    replay = await module.execute_plan(plan, engine=engine, apply=True)
    assert replay["deals"][0]["status"] == "already_applied"
    assert (await client.get(f"/api/deals/{item['deal_id']}")).json()["revision"] == detail["revision"]
    async with async_session() as db:
        assert module.RECEIPT_KEY in (await db.get(Deal, item["deal_id"])).metrics


async def test_later_save_failure_rolls_back_earlier_route_commits(client):
    from app.database import engine

    item, _ = await seed_plan(client)
    item["financing"]["measures"][0]["amount"] = 600000
    module = backfill_module()
    plan = module.BackfillPlan.model_validate({"version": 1, "deals": [item]})
    url = f"/api/deals/{item['deal_id']}"
    before = (await client.get(url)).json()
    with pytest.raises(module.BackfillFailure) as failure:
        await module.execute_plan(plan, engine=engine, apply=True)
    assert set(failure.value.report["deals"][0]) == {"deal_id", "revision", "current_package_id"}
    after = (await client.get(url)).json()
    assert after["revision"] == before["revision"]
    assert after["analysis"] == before["analysis"]
    assert (await client.get(url + "/review/draft")).json()["draft"] is None


async def test_guarded_refresh_validates_new_reading_and_can_rollback_it(client):
    import copy

    from app.database import async_session, engine
    from app.models import DealDocument
    from app.services.document_context import sha256_file

    item, doc_id = await seed_plan(client)
    async with async_session() as db:
        doc = await db.get(DealDocument, doc_id)
        expected_hash = sha256_file(doc.file_path)
        doc.extracted_text = "Earlier reading without value cells"
        await db.commit()
    url = f"/api/deals/{item['deal_id']}"
    packet = (await client.get(url + "/review/packet")).json()["packet"]
    detail = (await client.get(url)).json()
    item.update(expected_revision=detail["revision"], package_id=packet["package_id"],
                refresh_sources=[{"document_id": doc_id, "expected_file_sha256": expected_hash}],
                rebind_after_refresh=True)
    item["review"]["package_id"] = packet["package_id"]
    module = backfill_module()
    wrong_hash = copy.deepcopy(item)
    wrong_hash["refresh_sources"][0]["expected_file_sha256"] = "0" * 64
    with pytest.raises(module.BackfillFailure):
        await module.execute_plan(
            module.BackfillPlan.model_validate({"version": 1, "deals": [wrong_hash]}), engine=engine, apply=True,
        )
    plan = module.BackfillPlan.model_validate({"version": 1, "deals": [item]})
    report = await module.execute_plan(plan, engine=engine)
    assert report["status"] == "validated"
    assert report["deals"][0]["refreshed_documents"] == [doc_id]
    async with async_session() as db:
        assert (await db.get(DealDocument, doc_id)).extracted_text == "Earlier reading without value cells"
    saved = await module.execute_plan(plan, engine=engine, apply=True)
    assert saved["status"] == "applied"
    async with async_session() as db:
        assert "B2=100000" in (await db.get(DealDocument, doc_id)).extracted_text
    assert (await client.get(url)).json()["analysis"]["facts"]["deal_structure.minimum_investment"]["value"] == 100000


async def test_failed_preflight_reports_all_target_revisions_and_selected_issues(client):
    from app.database import engine

    first, _ = await seed_plan(client)
    second, _ = await seed_plan(client)
    module = backfill_module()
    first["expected_revision"] += 1
    plan = module.BackfillPlan.model_validate({"version": 1, "deals": [first, second]})
    with pytest.raises(module.BackfillFailure) as stale:
        await module.execute_plan(plan, engine=engine, apply=True)
    assert [row["deal_id"] for row in stale.value.report["deals"]] == [first["deal_id"], second["deal_id"]]
    assert all(row["revision"] and row["current_package_id"] for row in stale.value.report["deals"])
    first["expected_revision"] -= 1
    first["approve_paths"].append("project_details.unit_count")
    plan = module.BackfillPlan.model_validate({"version": 1, "deals": [first, second]})
    with pytest.raises(module.BackfillFailure) as blocked:
        await module.execute_plan(plan, engine=engine)
    report = blocked.value.report
    assert report["deals"][0]["blocked_selected"][0]["path"] == "project_details.unit_count"
    assert "source_excerpt" not in str(report)
    assert "review" not in report["deals"][0]


async def test_independent_diagnostic_continues_after_failures_and_rolls_back_every_deal(client):
    import copy

    from sqlalchemy import select
    from app.database import async_session, engine
    from app.models import AnalysisSnapshot, Deal, DealDocument, ReviewJob

    items = [(await seed_plan(client))[0] for _ in range(3)]
    items[0]["approve_paths"].append("project_details.unit_count")
    items[1]["financing"]["measures"][0]["amount"] = 600000
    module = backfill_module()
    plan = module.BackfillPlan.model_validate({"version": 1, "deals": items})
    original_plan = copy.deepcopy(plan.model_dump())

    async def database_state():
        state = {}
        async with async_session() as db:
            for model in (Deal, DealDocument, ReviewJob, AnalysisSnapshot):
                rows = (await db.execute(select(model).order_by(*model.__table__.primary_key.columns))).scalars().all()
                state[model.__tablename__] = [
                    {column.name: copy.deepcopy(getattr(row, column.name)) for column in model.__table__.columns}
                    for row in rows
                ]
        return state

    before = await database_state()
    report = await module.diagnose_plan(plan, engine=engine)
    assert report["mode"] == "diagnostic_dry_run"
    assert report["status"] == "failed"
    assert report["failed_deals"] == 2 and report["validated_deals"] == 1
    assert [row["deal_id"] for row in report["deals"]] == [item["deal_id"] for item in items]
    assert report["deals"][0]["blocked_selected"][0]["path"] == "project_details.unit_count"
    assert report["deals"][1]["status"] == "failed"
    assert report["deals"][2]["status"] == "validated"
    assert report["deals"][2]["analysis"]["accepted_fact_count"] > 0
    assert "source_excerpt" not in str(report)
    assert plan.model_dump() == original_plan
    assert await database_state() == before
