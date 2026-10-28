"""Conservative identity hints from explicit source labels, never financial guesses."""
import copy
import re
from sqlalchemy import select, func
from app.models import Deal, DealDocument, Developer
from app.services.document_versions import review_documents

LABELS = {"project_name": r"project name|property name", "sponsor": r"sponsor|developer",
          "city": r"city", "state": r"state", "property_type": r"property type"}
PROPERTY_TYPES = {"multifamily", "mixed-use", "office", "retail", "industrial", "hospitality", "land", "other"}


def identity_candidates(documents):
    candidates = {key: [] for key in LABELS}
    for doc in review_documents(documents):
        page = None
        for line in (doc.extracted_text or "").splitlines():
            marker = re.search(r"--- Page (\d+) ---", line)
            if marker:
                page = int(marker[1])
            for key, labels in LABELS.items():
                match = re.fullmatch(rf"\s*(?:{labels})\s*:\s*([^\r\n]{{2,180}}?)\s*", line, re.IGNORECASE)
                if match and not re.search(r"https?://|\b(unknown|tbd|n/a)\b", match[1], re.IGNORECASE):
                    candidates[key].append({"value": match[1].strip(), "document_id": doc.id,
                                            "document_name": doc.filename, "page": page, "excerpt": line.strip()})
    return candidates


async def populate_intake_identity(db, deal_id):
    deal = await db.get(Deal, deal_id)
    intake = copy.deepcopy((deal.metrics or {}).get("_intake")) if deal else None
    if not intake or deal.deleted_at is not None:
        return
    docs = (await db.execute(select(DealDocument).where(DealDocument.deal_id == deal_id))).scalars().all()
    candidates = identity_candidates(docs)
    previous = intake.get("auto_fields", {})
    automatic, conflicts = {}, []
    for key, items in candidates.items():
        values = {item["value"].casefold() for item in items}
        if len(values) > 1:
            conflicts.append(key)
        value = items[0]["value"] if len(values) == 1 else None
        attr = "developer_id" if key == "sponsor" else key
        current = getattr(deal, attr)
        old = previous.get(key, {}).get("stored_value")
        editable = current == old if key in previous else (
            current == intake.get("initial_name") and intake.get("name_origin") == "filename" if key == "project_name"
            else current in (None, "", "other") if key == "property_type" else current in (None, ""))
        if not editable:
            continue
        if not value:
            if key in previous:
                setattr(deal, attr, intake.get("initial_name", "New deal") if key == "project_name" else "other" if key == "property_type" else None if key == "sponsor" else "")
            continue
        if key == "property_type" and value.lower() not in PROPERTY_TYPES:
            continue
        stored = value.lower() if key == "property_type" else value
        if key == "sponsor":
            sponsor = (await db.execute(select(Developer).where(func.lower(Developer.name) == value.lower(), Developer.deleted_at.is_(None)).order_by(Developer.id))).scalars().first()
            if not sponsor:
                sponsor = Developer(name=value)
                db.add(sponsor)
                await db.flush()
            stored = sponsor.id
        setattr(deal, attr, stored)
        automatic[key] = {"stored_value": stored, "sources": items}
    # Retain evidence labels for untouched, manually edited fields without reclaiming them.
    intake["auto_fields"] = {**{key: meta for key, meta in previous.items() if key not in candidates or getattr(deal, "developer_id" if key == "sponsor" else key) == meta["stored_value"]}, **automatic}
    intake["identity_conflicts"] = conflicts
    deal.metrics = {**(deal.metrics or {}), "_intake": intake}
