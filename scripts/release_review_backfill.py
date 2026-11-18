"""Run a supplied review plan during a maintenance release, outside HTTP."""
from __future__ import annotations

import asyncio
import base64
import gzip
import io
import json
import logging
import os

from sqlalchemy import select

from app.database import async_session, engine
from app.models import Deal
from app.services.analysis import digest
from scripts.review_backfill import BackfillFailure, BackfillPlan, diagnose_plan, execute_plan


log = logging.getLogger("kenyon.review_backfill")
MAX_PLAN_BYTES = 512_000


def start_review_backfill():
    encoded_plan = os.environ.pop("KENYON_REVIEW_BACKFILL_PLAN", "")
    mode = os.environ.pop("KENYON_REVIEW_BACKFILL_MODE", "validate")
    if not encoded_plan:
        return None
    return asyncio.create_task(_run(encoded_plan, mode), name="review-backfill")


async def _run(encoded_plan, mode):
    try:
        if mode not in {"validate", "apply"} or len(encoded_plan) > MAX_PLAN_BYTES:
            raise ValueError("Invalid review maintenance configuration.")
        compressed = base64.b64decode(encoded_plan, validate=True)
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as plan_file:
            body = plan_file.read(MAX_PLAN_BYTES + 1)
        if len(body) > MAX_PLAN_BYTES:
            raise ValueError("Review maintenance plan exceeds the size limit.")
        plan = BackfillPlan.model_validate_json(body)
        approved_plan_digest = digest(plan.model_dump())
        if mode == "validate":
            # Preview against current revisions, while the source package guard
            # stays fixed. The apply release must supply these exact revisions.
            ids = [item.deal_id for item in plan.deals]
            async with async_session() as db:
                revisions = dict((await db.execute(
                    select(Deal.id, Deal.revision).where(Deal.id.in_(ids))
                )).all())
            plan = plan.model_copy(update={"deals": [
                item.model_copy(update={"expected_revision": revisions.get(item.deal_id, item.expected_revision)})
                for item in plan.deals
            ]})
        operation = diagnose_plan(plan, engine=engine) if mode == "validate" else execute_plan(plan, engine=engine, apply=True)
        result = await asyncio.wait_for(operation, timeout=120)
        result["approved_plan_digest"] = approved_plan_digest
    except BackfillFailure as exc:
        result = exc.report
    except Exception as exc:
        # Database and validation exceptions can include original inputs.
        result = {"status": "failed", "error_type": type(exc).__name__}
    deals = result.pop("deals", [])
    log.info("Review backfill result %s", json.dumps(result, separators=(",", ":")))
    for deal in deals:
        review = deal.pop("review", [])
        deal["selected_values"] = sum(row["selected"] and not row["issue"] for row in review)
        deal["row_issues"] = [
            {"path": row["path"], "issue": row["issue"]} for row in review if row["issue"]
        ]
        log.info("Review backfill deal %s", json.dumps(deal, separators=(",", ":")))
