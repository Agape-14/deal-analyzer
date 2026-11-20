"""Explicit source resolutions preserve prior values and still check quotes."""

import importlib
import io
import sys

import pytest
from reportlab.pdfgen.canvas import Canvas


@pytest.mark.asyncio
async def test_repair_saved_candidate_checks_exact_source_and_preserves_alias_history(client):
    from app.database import async_session
    from app.models import Deal
    from app.services.analysis import flatten
    from app.services.review_drafts import DRAFT_KEY, ReviewResult, draft_record, load_documents, package_identity

    sys.modules.pop("scripts.review_repair", None)
    repair = importlib.import_module("scripts.review_repair")
    sale_path = "target_returns.sale_scenario.sale_irr"
    ltv_path = "deal_structure.ltv"
    deal_id = (await client.post("/api/deals", json={"project_name": "Synthetic review repair"})).json()["id"]
    pdf = io.BytesIO()
    canvas = Canvas(pdf)
    canvas.drawString(60, 700, "Optional investor sale projection: 17% IRR.")
    canvas.drawString(60, 675, "Permanent loan-to-value at stabilization: 65.8%.")
    canvas.save()
    uploaded = await client.post(f"/api/deals/{deal_id}/documents/upload", files={
        "file": ("memo.pdf", pdf.getvalue(), "application/pdf"),
    })
    assert uploaded.status_code == 200, uploaded.text

    async with async_session() as db:
        deal = await db.get(Deal, deal_id)
        docs = await load_documents(db, deal_id)
        source_id = docs[0].id
        deal.metrics = {
            "target_returns": {"sale_scenario": {"sale_irr": 14}, "sale_scenario.sale_irr": 11},
            "deal_structure": {"ltv": 68, "loan_to_cost": 68},
            "_locks": {ltv_path: True},
        }
        await db.commit()
        package = package_identity(deal, docs)
        result = ReviewResult.model_validate({
            "package_id": package,
            "facts": [
                {"path": sale_path, "value": 17, "source_doc_id": source_id, "source_page": 1,
                 "source_excerpt": "Optional investor sale projection: 17% IRR.",
                 "scenario": "sale", "investor_class": "Investors", "period": "Illustrative exit"},
                {"path": ltv_path, "value": 65.8, "source_doc_id": source_id, "source_page": 1,
                 "source_excerpt": "Permanent loan-to-value at stabilization: 65.8%.",
                 "debt_phase": "permanent", "period": "Stabilization"},
            ],
        })
        item = repair.RepairDeal(
            deal_id=deal_id, expected_revision=deal.revision, package_id=package,
            fields=[repair.RepairSelector(path=path, source_doc_id=source_id, source_page=1)
                    for path in (sale_path, ltv_path)],
        )
        wrong = result.model_copy(update={"facts": [
            result.facts[0].model_copy(update={"value": 19}), result.facts[1],
        ]})
        deal.metrics = {**deal.metrics, DRAFT_KEY: draft_record(wrong, "codex")}
        with pytest.raises(repair.RepairBlocked, match="sale_irr"):
            repair._repair_review_rows(deal, docs, item)
        assert sorted(flatten(deal.metrics)[sale_path]) == [11, 14]

        deal.metrics = {**deal.metrics, DRAFT_KEY: draft_record(result, "codex")}
        metrics = repair._repair_review_rows(deal, docs, item)
        assert flatten(metrics)[sale_path] == [17]
        assert flatten(metrics)[ltv_path] == [65.8]
        assert flatten(metrics)["deal_structure.loan_to_cost"] == [68]
        assert metrics["_locks"][ltv_path] is True
        assert metrics["_fact_context"][sale_path]["period"] == "Illustrative exit"
        assert metrics["_provenance"][sale_path]["source_doc_id"] == source_id
        assert metrics["_provenance"][sale_path]["last_source_check"]["status"] == "confirmed"
        assert metrics["_field_history"][0]["old_value"] == [14, 11]
        assert DRAFT_KEY not in metrics
