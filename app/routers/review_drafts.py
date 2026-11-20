"""Download and approve a document review through the analyst deal API."""
import copy
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.auth import current_user
from app.database import get_db
from app.permissions import require_analyst
from app.routers.analysis import get_deal
from app.routers.field_edits import _refresh_integrity
from app.services.analysis_store import document_manifest
from app.services.data_integrity import now_iso
from app.services.return_crosscheck import CROSSCHECK_KEY, checked_return_crosscheck
from app.services.review_findings import FINDINGS_KEY, apply_findings, project_findings
from app.services.review_jobs import public_pipeline
from app.services.review_drafts import (
    ATTEMPT_KEY, DRAFT_KEY, MAX_RESULT_BYTES, ReviewError, ReviewResult, apply_rows, codex_packet,
    draft_record, draft_view, load_documents, package_identity, review_packet,
)

router = APIRouter(dependencies=[Depends(require_analyst)])


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
    paths: list[str] = Field(default_factory=list, max_length=200)
    candidate_ids: list[Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]] = Field(default_factory=list, max_length=200)
    coverage_groups: list[str] = Field(default_factory=list, max_length=4)
    finding_ids: list[str] = Field(default_factory=list, max_length=20)
    apply_return_crosscheck: bool = False


@router.post("/{deal_id}/review/approve")
async def approve_draft(deal_id: int, approval: ReviewApproval, db: AsyncSession = Depends(get_db),
                        request: Request = None):
    deal = await get_deal(deal_id, db)
    if deal.revision != approval.expected_revision:
        raise HTTPException(409, "The deal changed. Reload the review before applying values.")
    docs = await load_documents(db, deal.id)
    draft = draft_view(deal, docs)["draft"]
    if not draft or draft["stale"] or draft["id"] != approval.draft_id:
        raise HTTPException(409, "This draft is no longer current. Refresh the review before applying values.")
    paths = set(approval.paths)
    candidate_ids = set(approval.candidate_ids)
    coverage_groups = set(approval.coverage_groups)
    finding_ids = set(approval.finding_ids)
    if not (paths or candidate_ids or coverage_groups or finding_ids or approval.apply_return_crosscheck):
        raise HTTPException(422, "Select values, findings or checks to apply.")
    rows = [row for row in draft["rows"] if not row["issue"] and row["path"] in paths]
    if len(rows) != len(paths):
        raise HTTPException(422, "Some selected values have unresolved source checks.")
    chosen = [row for row in draft["rows"] if row.get("candidate_id") in candidate_ids and not row["candidate_issue"]]
    if len(chosen) != len(candidate_ids):
        raise HTTPException(422, "Some selected options need another source check.")
    chosen_paths = {row["path"] for row in chosen}
    if len(chosen_paths) != len(chosen) or chosen_paths & paths:
        raise HTTPException(422, "Choose only one value per conflicting field.")
    paths.update(chosen_paths)
    rows.extend(chosen)
    coverage = [row for row in draft["coverage"] if not row["issue"] and row["group"] in coverage_groups]
    if len(coverage) != len(coverage_groups):
        raise HTTPException(422, "Some selected group assessments have unresolved source checks.")
    finding_rows = [row for row in draft["findings"] if not row["issue"] and row["id"] in finding_ids]
    if len(finding_rows) != len(finding_ids):
        raise HTTPException(422, "Some selected findings have unresolved source checks.")
    record = deal.metrics[DRAFT_KEY]
    result = ReviewResult.model_validate(record["result"])
    metrics = apply_rows(deal, docs, rows, coverage)
    if chosen:
        user = current_user(request) if request is not None else None
        actor = (user or {}).get("u") or "Analyst"
        for row in chosen:
            path = row["path"]
            metrics["_provenance"][path]["conflict_review"] = {
                "selected_id": row["candidate_id"],
                "at": now_iso(),
                "by": actor,
                "options": [
                    {key: option[key] for key in ("candidate_id", "value", "evidence", "context")}
                    for option in draft["rows"] if option["path"] == path
                ],
            }
    try:
        apply_findings(metrics, finding_rows)
        if approval.apply_return_crosscheck:
            if result.return_crosscheck is None or not (draft["return_crosscheck"] or {}).get("value"):
                raise ValueError("The selected return check has unresolved source checks.")
            metrics[CROSSCHECK_KEY] = checked_return_crosscheck(result.return_crosscheck, docs, document_manifest(docs))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    _refresh_integrity(deal, metrics)
    metrics = deal.metrics
    new_package_id = package_identity(deal, docs)
    remaining = [fact for fact in result.facts if fact.path not in paths]
    remaining_coverage = [row for row in result.coverage if row.group not in coverage_groups]
    remaining_findings = [
        item for item, row in zip(result.findings, draft["findings"]) if row["id"] not in finding_ids
    ]
    remaining_check = result.return_crosscheck if not approval.apply_return_crosscheck else None
    if remaining or remaining_coverage or remaining_findings or remaining_check:
        updated = result.model_copy(update={"package_id": new_package_id, "facts": remaining,
            "coverage": remaining_coverage, "findings": remaining_findings, "return_crosscheck": remaining_check})
        metrics[DRAFT_KEY] = draft_record(updated, record["provider"], record.get("usage"))
    attempt = metrics.get(ATTEMPT_KEY) or {}
    if attempt.get("completed") and attempt.get("package_id") == result.package_id:
        metrics[ATTEMPT_KEY] = {**attempt, "package_id": new_package_id}
    try:
        await db.commit()
    except StaleDataError:
        await db.rollback()
        raise HTTPException(409, "The deal changed. Reload the review before applying values.") from None
    return {**_public_draft(deal, docs), "applied": len(rows), "coverage_applied": len(coverage),
            "findings_applied": len(finding_rows), "return_crosscheck_applied": approval.apply_return_crosscheck}


class FindingDecision(BaseModel):
    expected_revision: int = Field(ge=1)
    action: Literal["prefer_source", "keep_open", "record_note", "acknowledge"] = "record_note"
    decision: str = Field(default="", max_length=1000)
    source_index: int | None = Field(default=None, ge=0, strict=True)


@router.post("/{deal_id}/review/findings/{finding_id}/resolve")
async def resolve_finding(deal_id: int, finding_id: str, data: FindingDecision, request: Request,
                          db: AsyncSession = Depends(get_db)):
    deal = await get_deal(deal_id, db)
    if deal.revision != data.expected_revision:
        raise HTTPException(409, "The deal changed. Reload before saving a decision.")
    decision = data.decision.strip()
    if data.action == "record_note" and len(decision) < 3:
        raise HTTPException(422, "Describe your decision and its basis.")
    docs = await load_documents(db, deal.id)
    manifest = document_manifest(docs)
    metrics = copy.deepcopy(deal.metrics or {})
    before = next((item for item in project_findings(metrics, manifest) if item["id"] == finding_id), None)
    if before is None:
        raise HTTPException(404, "Source finding not found.")
    if before["status"] == "needs_review":
        raise HTTPException(409, "Recheck the finding against the current source version before saving a decision.")
    if data.action == "prefer_source":
        if before["kind"] != "conflict" or data.source_index is None or data.source_index >= len(before["evidence"]):
            raise HTTPException(422, "Choose one of the current cited sources.")
    elif data.source_index is not None:
        raise HTTPException(422, "Only a source choice can select a citation.")
    if data.action == "acknowledge" and before["kind"] != "source_note":
        raise HTTPException(422, "Choose a source or leave the conflict open.")
    actor = (current_user(request) or {}).get("u") or "Analyst"
    record = {"action": data.action, "text": decision, "at": now_iso(), "by": actor}
    if data.source_index is not None:
        record["source_index"] = data.source_index
    previous_package = package_identity(deal, docs)
    metrics[FINDINGS_KEY][finding_id]["decision"] = record
    deal.metrics = metrics
    new_package = package_identity(deal, docs)
    draft = metrics.get(DRAFT_KEY) or {}
    pending = draft.get("result") or {}
    # A source preference changes the audit record, so carry current
    # unapplied values forward with their unchanged source checks.
    if pending.get("package_id") == previous_package:
        updated = ReviewResult.model_validate({**pending, "package_id": new_package})
        metrics[DRAFT_KEY] = draft_record(updated, draft["provider"], draft.get("usage"))
    attempt = metrics.get(ATTEMPT_KEY) or {}
    if attempt.get("completed") and attempt.get("package_id") == previous_package:
        metrics[ATTEMPT_KEY] = {**attempt, "package_id": new_package}
    try:
        await db.commit()
    except StaleDataError:
        await db.rollback()
        raise HTTPException(409, "The deal changed. Reload before saving a decision.") from None
    return {"revision": deal.revision, "findings": project_findings(deal.metrics, manifest)}
