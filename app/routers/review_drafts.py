"""Download and approve a document review through the authenticated deal API."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.routers.analysis import get_deal
from app.routers.field_edits import _refresh_integrity
from app.services.review_jobs import public_pipeline
from app.services.review_drafts import (
    ATTEMPT_KEY, DRAFT_KEY, MAX_RESULT_BYTES, ReviewError, ReviewResult, apply_rows, codex_packet,
    draft_record, draft_view, load_documents, package_identity, review_packet,
)

router = APIRouter()


def _public_draft(deal, docs):
    job = deal.review_job
    status = public_pipeline(deal) if job and job.mode == "openai" else {}
    return {**draft_view(deal, docs), "job": {"status": job.status, "error": status.get("error")} if status else None}


@router.get("/{deal_id}/review/packet")
async def download_packet(deal_id: int, db: AsyncSession = Depends(get_db)):
    deal = await get_deal(deal_id, db)
    docs = await load_documents(db, deal.id)
    try:
        packet = review_packet(deal, docs)
    except ReviewError as exc:
        raise HTTPException(409, str(exc)) from None
    return Response(codex_packet(packet), media_type="application/json", headers={
        "Content-Disposition": f'attachment; filename="deal-{deal.id}-review-packet.json"',
        "Cache-Control": "private, no-store",
    })


@router.get("/{deal_id}/review/draft")
async def get_draft(deal_id: int, response: Response, db: AsyncSession = Depends(get_db)):
    deal = await get_deal(deal_id, db)
    response.headers["Cache-Control"] = "private, no-store"
    return _public_draft(deal, await load_documents(db, deal.id))


@router.post("/{deal_id}/review/draft")
async def import_draft(deal_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    deal = await get_deal(deal_id, db)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_RESULT_BYTES:
            raise HTTPException(413, "The Codex result exceeds the import size limit.")
        body.extend(chunk)
    try:
        result = ReviewResult.model_validate_json(body)
    except ValidationError:
        raise HTTPException(422, "Choose the deal-review-result.json file that Codex produced.") from None
    docs = await load_documents(db, deal.id)
    if result.package_id != package_identity(deal, docs):
        raise HTTPException(409, "This result is for a different or older source package. Download a new packet.")
    deal.metrics = {**(deal.metrics or {}), DRAFT_KEY: draft_record(result, "codex")}
    await db.commit()
    return _public_draft(deal, docs)


class ReviewApproval(BaseModel):
    draft_id: str = Field(max_length=64)
    expected_revision: int
    paths: list[str] = Field(min_length=1, max_length=200)


@router.post("/{deal_id}/review/approve")
async def approve_draft(deal_id: int, approval: ReviewApproval, db: AsyncSession = Depends(get_db)):
    deal = await get_deal(deal_id, db)
    if deal.revision != approval.expected_revision:
        raise HTTPException(409, "The deal changed. Reload the review before applying values.")
    docs = await load_documents(db, deal.id)
    draft = draft_view(deal, docs)["draft"]
    if not draft or draft["stale"] or draft["id"] != approval.draft_id:
        raise HTTPException(409, "This draft is no longer current. Refresh the review before applying values.")
    paths = set(approval.paths)
    rows = [row for row in draft["rows"] if not row["issue"] and row["path"] in paths]
    if len(rows) != len(paths):
        raise HTTPException(422, "Some selected values have unresolved source checks.")
    record = deal.metrics[DRAFT_KEY]
    result = ReviewResult.model_validate(record["result"])
    metrics = apply_rows(deal, docs, rows)
    _refresh_integrity(deal, metrics)
    new_package_id = package_identity(deal, docs)
    remaining = [fact for fact in result.facts if fact.path not in paths]
    if remaining:
        updated = ReviewResult(package_id=new_package_id, facts=remaining)
        metrics[DRAFT_KEY] = draft_record(updated, record["provider"], record.get("usage"))
    attempt = metrics.get(ATTEMPT_KEY) or {}
    if attempt.get("completed") and attempt.get("package_id") == result.package_id:
        metrics[ATTEMPT_KEY] = {**attempt, "package_id": new_package_id}
    await db.commit()
    return {**_public_draft(deal, docs), "applied": len(rows)}