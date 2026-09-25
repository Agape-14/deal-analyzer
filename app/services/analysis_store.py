"""Persist immutable analysis revisions in the transaction that changed inputs."""
from __future__ import annotations

import copy
import hashlib
from datetime import datetime, timezone

from sqlalchemy import inspect, select

from app.models import AnalysisSnapshot, Deal, DealDocument
from app.services.analysis import build_analysis


def snapshot_inputs(metrics):
    # Keep the source/decision record, not provider caches or transient jobs.
    omitted = {"_pipeline", "_document_review_cache", "_verification_cache", "_math_checks", "_data_quality"}
    return copy.deepcopy({k: v for k, v in (metrics or {}).items() if k not in omitted})


def collect_changes(session):
    from app.services.review_jobs import assert_lease
    assert_lease(session)
    pending = session.info.setdefault("analysis_pending", {})
    doc_deals = set()
    for obj in list(session.new) + list(session.dirty) + list(session.deleted):
        if isinstance(obj, Deal) and obj not in session.deleted:
            state = inspect(obj)
            fact_change = obj in session.new or any(state.attrs[key].history.has_changes() for key in ("metrics", "property_type"))
            score_change = state.attrs.scores.history.has_changes()
            if fact_change or score_change:
                previous = pending.get(obj, False)
                pending[obj] = previous or score_change
        elif isinstance(obj, DealDocument) and obj.deal_id:
            doc_deals.add(obj.deal_id)
    with session.no_autoflush:
        for deal_id in doc_deals:
            deal = session.get(Deal, deal_id)
            if deal and deal not in session.deleted:
                pending.setdefault(deal, False)


def document_manifest(documents):
    return sorted([
        {"id": doc.id, "filename": doc.filename, "page_count": doc.page_count or 0,
         "content_hash": doc.file_sha256 or doc.content_fingerprint or hashlib.sha256((doc.extracted_text or "").encode()).hexdigest()}
        for doc in documents
    ], key=lambda d: d["id"])


def persist_changes(session):
    pending = session.info.pop("analysis_pending", {})
    for deal, scores_changed in pending.items():
        if inspect(deal).deleted:
            continue
        documents = session.scalars(select(DealDocument).where(DealDocument.deal_id == deal.id)).all()
        snapshot = build_analysis(deal.metrics, document_manifest(documents), deal.property_type)
        previous = deal.analysis_snapshot if isinstance(deal.analysis_snapshot, dict) else {}
        if snapshot["input_hash"] != previous.get("input_hash"):
            version = (deal.analysis_version or 0) + 1
            snapshot["version"] = version
            snapshot["created_at"] = datetime.now(timezone.utc).isoformat()
            snapshot["changes"] = [
                {"path": path, "previous_value": (previous.get("facts", {}).get(path) or {}).get("value"),
                 "value": (snapshot["facts"].get(path) or {}).get("value"),
                 "previous_state": (previous.get("facts", {}).get(path) or {}).get("state"),
                 "state": (snapshot["facts"].get(path) or {}).get("state", "removed")}
                for path in sorted(set(snapshot["facts"]) | set(previous.get("facts", {})))
                if snapshot["facts"].get(path) != previous.get("facts", {}).get(path)
            ]
            deal.analysis_version = version
            deal.analysis_snapshot = snapshot
            session.add(AnalysisSnapshot(deal_id=deal.id, version=version, input_hash=snapshot["input_hash"], payload=copy.deepcopy(snapshot), input_metrics=snapshot_inputs(deal.metrics)))
