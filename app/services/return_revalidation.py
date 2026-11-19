"""Renew accepted return evidence when a refresh changed only reading metadata."""

from __future__ import annotations

import asyncio
import copy

from pydantic import ValidationError
from sqlalchemy import select

from app.models import AnalysisSnapshot
from app.services.analysis import ACCEPTED, RETURN_REVIEWS_KEY, build_analysis, identity, return_review_binding
from app.services.analysis_store import document_manifest
from app.services.document_context import sha256_file
from app.services.document_versions import review_documents
from app.services.return_schedules import (
    SCHEDULE_KEY, ReturnScheduleInput, active_sources_fingerprint, checked_return_schedule,
)
from app.services.source_evidence import fresh_audit_evidence


def _byte_signature(manifest):
    active = [doc for doc in manifest if doc.get("included_in_review", doc.get("source_role", "active") == "active")]
    if not active or any(not doc.get("file_sha256") for doc in active):
        return None
    return tuple(sorted((doc["id"], doc["file_sha256"]) for doc in active))


def _published_return(analysis, path):
    returns = analysis.get("returns") or {}
    return any(returns.get(key) is not None and returns.get(f"{key}_path") == path
               for key in ("target_irr", "cash_on_cash", "target_equity_multiple"))


def _renew_scope(record, path, analysis, metrics, sources, manifest, source_set):
    from app.routers.analysis import ScopedReturn, cited_return_value

    fact = analysis["facts"].get(path)
    if (not fact or fact["state"] not in ACCEPTED or not _published_return(analysis, path)
            or record.get("binding") != return_review_binding(metrics, path, fact["value"])):
        return None
    context = record.get("context") or {}
    old_citation = record.get("citation") or {}
    try:
        update = ScopedReturn.model_validate({
            "expected_revision": 1, "path": path, "action": "scope", **context,
            **{key: old_citation.get(key) for key in
               ("source_doc_id", "source_page", "source_sheet", "source_cell", "source_excerpt")},
        })
    except ValidationError:
        return None
    resolved = identity(path, fact["identity"]["unit"], context)
    if not context or any(getattr(resolved, key) != value for key, value in context.items()):
        return None
    citation, issue = fresh_audit_evidence(update.model_dump(), sources, manifest)
    if issue or cited_return_value(update, fact):
        return None
    return {**record, "citation": citation, "document_set": source_set}


async def revalidate_same_file_returns(db, deal, documents):
    """Rebind only previously published decisions proved by identical original bytes."""
    metrics = deal.metrics or {}
    manifest = document_manifest(documents)
    source_set = active_sources_fingerprint(manifest)
    schedule = metrics.get(SCHEDULE_KEY)
    pending_schedule = isinstance(schedule, dict) and schedule.get("review_document_set") != source_set
    pending_scopes = {
        path: record for path, record in (metrics.get(RETURN_REVIEWS_KEY) or {}).items()
        if isinstance(record, dict) and record.get("action") == "scope" and record.get("document_set") != source_set
    }
    if not pending_schedule and not pending_scopes:
        return []
    signature = _byte_signature(manifest)
    if not signature:
        return []
    sources = review_documents(documents)
    actual = await asyncio.to_thread(
        lambda: tuple(sorted((doc.id, sha256_file(doc.file_path or "")) for doc in sources)),
    )
    if actual != signature:
        return []
    with db.no_autoflush:
        snapshots = (await db.execute(
            select(AnalysisSnapshot).where(AnalysisSnapshot.deal_id == deal.id)
            .order_by(AnalysisSnapshot.version.desc()).limit(60)
        )).scalars().all()
    current = build_analysis(metrics, manifest, deal.property_type)
    updated = copy.deepcopy(metrics)
    changed = []
    for snapshot in snapshots:
        historical = snapshot.payload or {}
        old_documents = historical.get("documents") or []
        if _byte_signature(old_documents) != signature:
            continue
        old_set = active_sources_fingerprint(old_documents)
        inputs = snapshot.input_metrics or {}
        if (pending_schedule and historical.get("return_schedule") and inputs.get(SCHEDULE_KEY) == schedule
                and schedule.get("review_document_set") == old_set
                and current["primary_strategy"] == historical.get("primary_strategy")
                and current["investor_class"] == historical.get("investor_class")):
            try:
                candidate = ReturnScheduleInput.model_validate(schedule["schedule"])
                updated[SCHEDULE_KEY] = checked_return_schedule(candidate, sources, manifest)
            except (ValidationError, ValueError, KeyError):
                pass
            else:
                changed.append(SCHEDULE_KEY)
                pending_schedule = False
        for path, record in list(pending_scopes.items()):
            previous = (inputs.get(RETURN_REVIEWS_KEY) or {}).get(path)
            old_fact = (historical.get("facts") or {}).get(path) or {}
            current_fact = current["facts"].get(path) or {}
            if (previous != record or old_set != record.get("document_set")
                    or not _published_return(historical, path) or old_fact.get("value") != current_fact.get("value")
                    or any((old_fact.get("identity") or {}).get(key) != value
                           for key, value in (record.get("context") or {}).items())):
                continue
            refreshed = _renew_scope(record, path, current, metrics, sources, manifest, source_set)
            if refreshed:
                updated.setdefault(RETURN_REVIEWS_KEY, {})[path] = refreshed
                del pending_scopes[path]
                changed.append(path)
        if not pending_schedule and not pending_scopes:
            break
    if changed:
        from app.routers.field_edits import _refresh_integrity
        _refresh_integrity(deal, updated)
    return changed
