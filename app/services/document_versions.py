"""Document identity and explicit version choices, without deleting originals."""
from collections import defaultdict


def file_hash(doc):
    from app.services.document_context import sha256_file
    return (getattr(doc, "file_sha256", "") or (getattr(doc, "extraction_quality", None) or {}).get("file_sha256")
            or sha256_file(getattr(doc, "file_path", "") or ""))


def role(doc):
    return getattr(doc, "source_role", None) or "active"


def document_inventory(documents):
    """Only byte hashes prove duplication; names and extracted text do not."""
    documents = sorted(documents, key=lambda d: d.id or 0)
    groups, names = defaultdict(list), defaultdict(list)
    hashes = {doc.id: file_hash(doc) for doc in documents}
    for doc in documents:
        if hashes[doc.id]:
            groups[hashes[doc.id]].append(doc)
        names[doc.filename.casefold()].append(doc)
    canonical = {}
    for digest, group in groups.items():
        # Prefer a usable active copy so a failed legacy copy cannot hide it.
        canonical[digest] = min(group, key=lambda d: (
            role(d) != "active", (getattr(d, "extraction_quality", None) or {}).get("status") == "error",
            not bool(getattr(d, "extracted_text", "")), d.id or 0))
    result = {}
    for doc in documents:
        original = canonical.get(hashes[doc.id], doc)
        result[doc.id] = {
            "source_role": role(doc),
            "superseded_by_id": getattr(doc, "superseded_by_id", None),
            "version_note": getattr(doc, "version_note", "") or "",
            "duplicate_of_id": original.id if original.id != doc.id else None,
            "same_name_different_content": any(
                other.id != doc.id and hashes[other.id] and hashes[doc.id]
                and hashes[other.id] != hashes[doc.id] for other in names[doc.filename.casefold()]),
            "included_in_review": role(doc) == "active" and original.id == doc.id,
        }
    return result


def review_documents(documents):
    documents = list(documents or [])
    inventory = document_inventory(documents)
    return [doc for doc in documents if inventory[doc.id]["included_in_review"]]


def document_payloads(documents):
    documents = list(documents)
    inventory = document_inventory(documents)
    result = []
    for doc in documents:
        quality = doc.extraction_quality or {}
        result.append({
            "id": doc.id, "filename": doc.filename, "doc_type": doc.doc_type,
            "page_count": doc.page_count, "upload_date": doc.upload_date.isoformat() if doc.upload_date else None,
            "has_text": bool(doc.extracted_text), "file_sha256": file_hash(doc),
            **inventory[doc.id],
            "extraction_quality": {key: quality.get(key) for key in (
                "status", "error", "document_kind", "quality_score", "ocr_pages", "empty_pages")}
                if quality else None,
        })
    return result
