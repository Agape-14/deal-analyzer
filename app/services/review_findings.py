"""Save source findings and analyst decisions with their reviewed evidence."""

from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.source_evidence import fresh_audit_evidence, normalized_text


FINDINGS_KEY = "_review_findings"
MAX_FINDINGS = 100
FINDING_KINDS = ("conflict", "source_note")


class FindingCitation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    source_doc_id: int = Field(gt=0)
    source_excerpt: str = Field(min_length=8, max_length=1000)
    source_page: int | None = Field(default=None, gt=0)
    source_sheet: str | None = Field(default=None, min_length=1, max_length=200)
    source_cell: str | None = Field(default=None, pattern=r"^[A-Za-z]{1,3}[1-9]\d*$")

    @model_validator(mode="after")
    def check_locator(self):
        if self.source_page is not None:
            if self.source_sheet or self.source_cell:
                raise ValueError("A PDF citation uses its page alone.")
        elif not self.source_sheet or not self.source_cell:
            raise ValueError("A workbook citation needs its sheet and cell.")
        return self


class SourceFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    kind: Literal["conflict", "source_note"]
    title: str = Field(min_length=5, max_length=100)
    detail: str = Field(min_length=12, max_length=800)
    citations: list[FindingCitation] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def distinct_evidence(self):
        unique = {(c.source_doc_id, c.source_page, c.source_sheet, c.source_cell,
                   normalized_text(c.source_excerpt)) for c in self.citations}
        if len(unique) != len(self.citations) or self.kind == "conflict" and len(unique) < 2:
            raise ValueError("A conflict needs two distinct source citations.")
        return self


def findings_output_schema():
    string = {"type": "string"}
    record = {
        "source_doc_id": {"type": "integer"}, "source_excerpt": string,
        "source_page": {"type": ["integer", "null"]},
        "source_sheet": {"type": ["string", "null"]}, "source_cell": {"type": ["string", "null"]},
    }
    item = {
        "kind": {"type": "string", "enum": list(FINDING_KINDS)}, "title": string, "detail": string,
        "citations": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "properties": record, "required": list(record),
        }},
    }
    return {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "properties": item, "required": list(item),
    }}


def _active(documents):
    return [doc for doc in documents
            if doc.get("included_in_review", doc.get("source_role", "active") == "active")]


def _named_versions(active, names):
    return {name: sorted({doc["content_hash"] for doc in active if doc["filename"].casefold() == name})
            for name in sorted(names)}


def finding_rows(proposals, docs, manifest):
    from app.services.analysis import digest, evidence_for
    from app.services.document_versions import review_documents

    active = _active(manifest)
    sources = review_documents(docs)
    ids = [digest([finding.kind, normalized_text(finding.title)])[:24] for finding in proposals]
    counts = Counter(ids)
    rows = []
    for finding, key in zip(proposals, ids):
        issue = "Review this finding once per draft." if counts[key] > 1 else ""
        evidence = []
        for source in finding.citations:
            citation, error = fresh_audit_evidence(source.model_dump(), sources, active)
            items, locator_error = evidence_for(citation, active)
            issue = issue or error or locator_error
            evidence.extend(items)
        names = {item["document_name"].casefold() for item in evidence}
        rows.append({"id": key, "kind": finding.kind, "title": finding.title, "detail": finding.detail,
                     "evidence": evidence, "source_versions": _named_versions(active, names), "issue": issue})
    return rows


def apply_findings(metrics, rows):
    if not rows:
        return
    saved = dict(metrics.get(FINDINGS_KEY) or {})
    if len(set(saved) | {row["id"] for row in rows}) > MAX_FINDINGS:
        raise ValueError("This deal has reached its saved source findings limit.")
    for row in rows:
        entry = {key: value for key, value in row.items() if key != "issue"}
        previous = saved.get(row["id"]) or {}
        if all(previous.get(key) == value for key, value in entry.items()) and previous.get("decision"):
            entry["decision"] = previous["decision"]
        saved[row["id"]] = entry
    metrics[FINDINGS_KEY] = saved


def project_findings(metrics, manifest):
    records = metrics.get(FINDINGS_KEY)
    if not isinstance(records, dict):
        return []
    active = _active(manifest)
    active_sources = {(doc["id"], doc["content_hash"]) for doc in active}
    findings = []
    for entry in records.values():
        evidence, versions = entry["evidence"], entry["source_versions"]
        stale = (any((item["document_id"], item["content_hash"]) not in active_sources for item in evidence)
                 or versions != _named_versions(active, versions))
        status = "needs_review" if stale else "resolved" if entry.get("decision") else "current"
        findings.append({key: value for key, value in entry.items() if key != "source_versions"} | {"status": status})
    return sorted(findings, key=lambda row: (row["status"] != "needs_review", row["status"] == "resolved", row["title"], row["id"]))
