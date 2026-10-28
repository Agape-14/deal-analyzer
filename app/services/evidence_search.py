"""Bounded, literal retrieval from current, deduplicated source documents.

Retrieval exposes reported text, never promotes it into an accepted fact.
No provider request, generated answer, or instructions from a document execute.
"""
import re

from app.services.document_context import split_text_pages, sha256_text
from app.services.document_versions import review_documents, file_hash

STOP = set("a an the is are what which how when where who does do did can could would should will please tell me about of to and or for in on at with from this that these those have has it its my our we document documents deal terms summarize explain show find".split())
ALIASES = {
    "fees": {"fee", "fees", "compensation"}, "fee": {"fee", "fees", "compensation"},
    "liquidity": {"liquidity", "redemption", "transfer", "withdrawal", "lockup"},
    "dates": {"date", "closing", "deadline", "maturity"},
    "sponsor": {"sponsor", "manager", "developer"},
    "rent": {"rent", "rental", "lease"},
}


def search_terms(query):
    words = [word for word in re.findall(r"[a-z0-9]{2,}", query.lower()) if word not in STOP]
    terms = set(words[:20])
    for word in list(terms):
        terms.update(ALIASES.get(word, ()))
    return terms


def search_documents(documents, query, limit=6):
    terms = search_terms(query)
    if not terms:
        return []
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(t) for t in sorted(terms)) + r")\b", re.I)
    hits = []
    for doc in review_documents(documents)[:100]:
        text = (getattr(doc, "extracted_text", "") or "")[:2_000_000]
        sheet_markers = list(re.finditer(r"^--- Sheet: (.+) ---\s*$", text, re.M))
        sections = [(None, m[1], text[m.end():sheet_markers[i+1].start() if i+1 < len(sheet_markers) else len(text)]) for i, m in enumerate(sheet_markers)] if sheet_markers else [(page, None, body) for page, body in split_text_pages(text)]
        for page, sheet, body in sections:
            matches = list(pattern.finditer(body))
            if not matches:
                continue
            for match in matches[:3]:
                start = max(0, body.rfind("\n", 0, match.start()) + 1)
                end = body.find("\n", match.end())
                end = min(len(body) if end < 0 else end, start + 900)
                excerpt = body[start:end].strip()
                if not excerpt:
                    continue
                cell = re.search(r"\b([A-Z]{1,3}[1-9]\d*)\s*=", excerpt) if sheet else None
                hits.append({"document_id": doc.id, "document_name": doc.filename,
                             "page": page, "sheet": sheet, "cell": cell[1] if cell else None,
                             "excerpt": excerpt, "content_hash": file_hash(doc),
                             "text_hash": sha256_text(text), "source_role": "active",
                             "score": len(set(m.group().lower() for m in pattern.finditer(excerpt)))})
    unique = {}
    for hit in sorted(hits, key=lambda h: -h["score"]):
        unique.setdefault((hit["document_id"], hit["page"], hit["sheet"], hit["excerpt"]), hit)
    return list(unique.values())[:limit]
