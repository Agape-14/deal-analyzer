"""
Data integrity primitives for deal metrics.

This module is the single source of truth for three invariants that were
missing from the original pipeline:

  1. **Smart merge, not overwrite** — re-extracting metrics from a new
     document must never wipe out a prior value with null. If the new
     extraction returns null/None for a field that previously had a real
     value, the previous value survives.

  2. **Provenance tracking** — every field with a value knows where it
     came from. We attach a parallel `_provenance` tree to metrics with:
       - `source`: "extraction" | "verification" | "manual" | "calculated"
       - `source_doc_id`: which Document the value was extracted from
       - `source_doc_name`: filename for UI display
       - `source_page`: page number in the PDF, if known
       - `extracted_at`: ISO timestamp of the extraction
       - `confidence`: 0-100, from /verify when available
       - `verified_at`: last time /verify ran on this field
       - `status`: "extracted" | "confirmed" | "wrong" | "unverifiable"
       - `conflict`: null OR [{doc_id, doc_name, value}] when docs disagree
       - `locked`: true/false — manual edits become locked against re-extract

  3. **Conflict detection** — when multiple documents disagree on the same
     field, we keep every value seen (with its source) in the provenance
     tree and emit a red flag in validation.

The provenance tree is stored at `deal.metrics._provenance` so the UI can
render a per-field integrity badge. Keys under `_provenance` mirror the
metric path: `_provenance['deal_structure.ltv'] = {...}`.

Everything here is pure (no DB, no HTTP). Route handlers thread the data
through.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

# ----------------------------- constants --------------------------------- #

# Keys under `deal.metrics` that we treat as metadata, not metric values.
# Merges / validators skip these.
META_KEYS = {"_provenance", "_verification", "_locks", "_extraction_history", "validation_flags"}

# Sections of `deal.metrics` that contain user-facing metrics.
METRIC_SECTIONS = (
    "deal_structure",
    "target_returns",
    "project_details",
    "financial_projections",
    "market_location",
    "risk_assessment",
    "underwriting_checks",
    "sponsor_evaluation",
    "market_research",
)


@dataclass
class FieldProvenance:
    """Metadata about a single extracted field."""

    source: str = "extraction"                 # extraction | verification | manual | calculated
    source_doc_id: int | None = None
    source_doc_name: str = ""
    source_page: int | None = None
    extracted_at: str = ""
    confidence: int | None = None              # 0-100 from /verify
    verified_at: str | None = None
    status: str = "extracted"                  # extracted | confirmed | wrong | unverifiable | stale
    conflict: list[dict[str, Any]] | None = None
    locked: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = {
            "source": self.source,
            "source_doc_id": self.source_doc_id,
            "source_doc_name": self.source_doc_name,
            "source_page": self.source_page,
            "extracted_at": self.extracted_at,
            "confidence": self.confidence,
            "verified_at": self.verified_at,
            "status": self.status,
            "conflict": self.conflict,
            "locked": self.locked,
        }
        # Drop None/empty for tighter JSON
        return {k: v for k, v in d.items() if v not in (None, "", [])}


# ------------------------------- helpers --------------------------------- #

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_meaningful(v: Any) -> bool:
    """Does this value carry information (vs None / '' / [])."""
    if v is None:
        return False
    if isinstance(v, str) and v.strip() == "":
        return False
    if isinstance(v, (list, dict)) and len(v) == 0:
        return False
    return True


def _iter_metric_fields(metrics: dict[str, Any]) -> Iterable[tuple[str, str, Any]]:
    """Walk the metrics tree, yielding (section, field, value) for non-meta fields."""
    for section in METRIC_SECTIONS:
        block = metrics.get(section) or {}
        if not isinstance(block, dict):
            continue
        for field_name, value in block.items():
            yield section, field_name, value


# ------------------------------ smart merge ------------------------------ #

def smart_merge(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any],
    *,
    source_doc_id: int | None = None,
    source_doc_name: str = "",
    preserve_locks: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    """Merge a fresh extraction into the existing metrics tree.

    Rules:
      - If the incoming value is meaningful, it wins — UNLESS the field is
        locked (user manually edited it).
      - If the incoming value is None/empty and the existing value is
        meaningful, the existing value is preserved.
      - Unknown metadata keys on `existing` are preserved verbatim.
      - Provenance is refreshed for every field whose value was just set
        from `incoming`.
      - Returns (merged, changes) where changes is a list of dotted paths
        that actually changed.

    This is the single function every extraction path should use to land
    metrics back onto the deal. It eliminates the "re-extract nukes a
    good value" bug.
    """
    merged: dict[str, Any] = {}
    changes: list[str] = []

    # Copy meta first so we don't lose verification / locks / history
    existing = existing or {}
    for k in META_KEYS:
        if k in existing:
            merged[k] = existing[k]

    locks = (existing.get("_locks") or {}) if preserve_locks else {}
    provenance = dict(existing.get("_provenance") or {})

    for section in set([*METRIC_SECTIONS, *incoming.keys(), *existing.keys()]):
        if section in META_KEYS:
            continue
        new_section = incoming.get(section) or {}
        old_section = existing.get(section) or {}
        if not isinstance(new_section, dict):
            # Not a metric section — copy verbatim
            merged[section] = new_section
            continue

        out: dict[str, Any] = {}
        # Merge field-by-field across union of keys
        for key in set([*new_section.keys(), *(old_section or {}).keys()]):
            path = f"{section}.{key}"
            old_v = (old_section or {}).get(key)
            new_v = new_section.get(key)

            if locks.get(path):
                # User-locked field: keep old value, record that we honored the lock
                out[key] = old_v
                continue

            if _is_meaningful(new_v):
                # Fresh value wins
                if new_v != old_v:
                    changes.append(path)
                out[key] = new_v
                prov = FieldProvenance(
                    source="extraction",
                    source_doc_id=source_doc_id,
                    source_doc_name=source_doc_name,
                    extracted_at=now_iso(),
                    status="extracted",
                )
                provenance[path] = prov.to_dict()
            else:
                # Incoming is null/empty — preserve old
                out[key] = old_v
                # Keep existing provenance as-is

        merged[section] = out

    if provenance:
        merged["_provenance"] = provenance
    else:
        merged.pop("_provenance", None)

    return merged, changes


# --------------------------- conflict detection -------------------------- #

def detect_conflicts(
    per_doc_metrics: list[tuple[int, str, dict[str, Any]]],
    *,
    tolerance_pct: float = 0.02,
) -> dict[str, list[dict[str, Any]]]:
    """
    Given extractions from multiple documents, return a map of
    `section.field` → list of {doc_id, doc_name, value} for every field
    where two or more docs disagree.

    `per_doc_metrics` is a list of (doc_id, doc_name, metrics_dict).

    Numeric values within `tolerance_pct` of each other are not counted
    as conflicts (rounding is normal). Strings must match exactly.
    """
    conflicts: dict[str, list[dict[str, Any]]] = {}

    # Collect per-field values by path
    by_path: dict[str, list[dict[str, Any]]] = {}
    for doc_id, doc_name, mx in per_doc_metrics:
        for section, field_name, value in _iter_metric_fields(mx):
            if not _is_meaningful(value):
                continue
            path = f"{section}.{field_name}"
            by_path.setdefault(path, []).append(
                {"doc_id": doc_id, "doc_name": doc_name, "value": value}
            )

    for path, entries in by_path.items():
        if len(entries) < 2:
            continue
        # Group by "equivalent" values
        groups: list[list[dict[str, Any]]] = []
        for e in entries:
            placed = False
            for g in groups:
                if _values_equivalent(g[0]["value"], e["value"], tolerance_pct):
                    g.append(e)
                    placed = True
                    break
            if not placed:
                groups.append([e])
        if len(groups) > 1:
            conflicts[path] = entries

    return conflicts


def _values_equivalent(a: Any, b: Any, tol: float) -> bool:
    if a == b:
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if a == 0 or b == 0:
            return abs(a - b) < 1e-6
        return abs(a - b) / max(abs(a), abs(b)) <= tol
    return False


def conflicts_to_flags(conflicts: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Turn a conflict map into red validation flags for the UI."""
    flags: list[dict[str, Any]] = []
    for path, entries in conflicts.items():
        values_shown = ", ".join(
            f"{e['doc_name']}: {e['value']}" for e in entries[:3]
        )
        flags.append(
            {
                "severity": "red",
                "category": "Data conflict",
                "message": f"{path} disagrees across documents ({values_shown}). Verify which is current.",
            }
        )
    return flags


# ----------------------- verification persistence ----------------------- #

def stamp_verification(
    metrics: dict[str, Any],
    verification: dict[str, Any],
) -> dict[str, Any]:
    """Fold `/verify` audit_results into the provenance tree.

    For each audit entry we update `_provenance[section.field]` with:
      - status: confirmed | wrong | unverifiable | calculated | missing
      - verified_at: now
      - confidence: from the verification summary
      - source_page / source_doc_name if parseable from the free-text 'source'

    Does NOT mutate the metric values themselves — that's the job of
    `apply_corrections`. This just attaches the audit result so the UI
    can render per-field verification badges.
    """
    if not isinstance(metrics, dict) or not isinstance(verification, dict):
        return metrics
    prov = dict(metrics.get("_provenance") or {})
    confidence = None
    summary = verification.get("summary") or {}
    if isinstance(summary, dict):
        confidence = summary.get("confidence_score")

    verified_at = now_iso()

    for row in verification.get("audit_results", []) or []:
        if not isinstance(row, dict):
            continue
        section = row.get("section")
        field_name = row.get("field")
        if not section or not field_name:
            continue
        path = f"{section}.{field_name}"
        p = dict(prov.get(path) or {})
        status = str(row.get("status") or "").lower() or "extracted"
        p["status"] = status
        p["verified_at"] = verified_at
        if confidence is not None:
            p["confidence"] = confidence

        # Parse "Page N" out of the free-text source so the UI can link
        # to a specific PDF page.
        src = row.get("source")
        if isinstance(src, str) and src.strip():
            p.setdefault("verification_source", src.strip())
            page = _extract_page_number(src)
            if page is not None:
                p["source_page"] = page

        note = row.get("note")
        if note:
            p["verification_note"] = str(note)

        prov[path] = p

    metrics["_provenance"] = prov

    # Top-level verification summary, surfaced on the dashboard
    v_summary = {
        "verified_at": verified_at,
        "confidence": confidence,
        "totals": {
            "confirmed": 0,
            "wrong": 0,
            "unverifiable": 0,
            "calculated": 0,
            "missing": 0,
        },
    }
    for row in verification.get("audit_results", []) or []:
        status = str((row or {}).get("status") or "").lower()
        if status in v_summary["totals"]:
            v_summary["totals"][status] += 1
    metrics["_verification"] = v_summary
    return metrics


def _extract_page_number(s: str) -> int | None:
    """Pull the first 'Page N' or 'page N' token out of a verification source note."""
    import re

    m = re.search(r"[Pp]age\s+(\d+)", s)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


# ----------------------------- field locks ----------------------------- #

def set_lock(metrics: dict[str, Any], path: str, locked: bool) -> dict[str, Any]:
    """Toggle the user-lock on a single dotted field path."""
    locks = dict(metrics.get("_locks") or {})
    if locked:
        locks[path] = True
    else:
        locks.pop(path, None)
    metrics["_locks"] = locks
    # Reflect in provenance too so the UI doesn't have to cross-reference
    prov = dict(metrics.get("_provenance") or {})
    if path in prov and isinstance(prov[path], dict):
        prov[path]["locked"] = bool(locked)
        metrics["_provenance"] = prov
    return metrics


def mark_manual_edit(
    metrics: dict[str, Any], path: str, value: Any, *, lock: bool = True
) -> dict[str, Any]:
    """Apply a manual user edit to a metric, refresh provenance, and lock.

    Supports dotted paths like `deal_structure.ltv`. Creates the parent
    section dict if it doesn't exist.
    """
    section, _, field_name = path.partition(".")
    if not section or not field_name:
        return metrics
    block = dict(metrics.get(section) or {})
    block[field_name] = value
    metrics[section] = block

    prov = dict(metrics.get("_provenance") or {})
    prov[path] = {
        "source": "manual",
        "status": "manual",
        "extracted_at": now_iso(),
        "locked": bool(lock),
    }
    metrics["_provenance"] = prov
    if lock:
        set_lock(metrics, path, True)
    return metrics


# --------------------------- staleness --------------------------- #

def staleness_flags(metrics: dict[str, Any], documents: list, *, days_threshold: int = 60) -> list[dict[str, Any]]:
    """
    Emit validation flags for stale extractions.

    - If any metric's `extracted_at` is older than `days_threshold`, warn.
    - If a document was uploaded *after* the latest extraction, warn more
      loudly: "new documents available; re-run extraction."
    """
    flags: list[dict[str, Any]] = []
    prov = metrics.get("_provenance") or {}
    if not prov:
        return flags

    extraction_dates = [
        _parse_iso(p.get("extracted_at"))
        for p in prov.values()
        if isinstance(p, dict) and p.get("extracted_at")
    ]
    extraction_dates = [d for d in extraction_dates if d is not None]
    if not extraction_dates:
        return flags

    latest_extraction = max(extraction_dates)
    now = datetime.now(timezone.utc)
    age_days = (now - latest_extraction).days

    if age_days >= days_threshold:
        flags.append(
            {
                "severity": "yellow",
                "category": "Staleness",
                "message": (
                    f"Metrics last extracted {age_days} days ago. "
                    "Re-run /extract if newer documents are available."
                ),
            }
        )

    # Document newer than the latest extraction?
    for doc in documents or []:
        upload = getattr(doc, "upload_date", None)
        if upload and _to_aware(upload) > latest_extraction:
            flags.append(
                {
                    "severity": "yellow",
                    "category": "Staleness",
                    "message": (
                        f"'{getattr(doc, 'filename', 'document')}' uploaded after the last extraction. "
                        "Re-run /extract to incorporate it."
                    ),
                }
            )
            break  # One is enough; don't flood

    return flags


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # fromisoformat handles the +00:00 suffix in py3.11
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _to_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# --------------------------- quality summary --------------------------- #

def quality_summary(metrics: dict[str, Any]) -> dict[str, Any]:
    """
    Aggregate data-quality counters for the UI. Returns:
      total_fields, verified, extracted, calculated, manual,
      conflicting, locked, stale_days
    """
    prov = metrics.get("_provenance") or {}
    verification = metrics.get("_verification") or {}

    total = 0
    counters = {
        "verified": 0,
        "extracted": 0,
        "calculated": 0,
        "manual": 0,
        "conflicting": 0,
        "locked": 0,
        "wrong": 0,
        "unverifiable": 0,
    }
    for path, p in prov.items():
        if not isinstance(p, dict):
            continue
        total += 1
        status = p.get("status") or "extracted"
        source = p.get("source") or "extraction"
        if p.get("conflict"):
            counters["conflicting"] += 1
        if p.get("locked"):
            counters["locked"] += 1
        if status == "confirmed":
            counters["verified"] += 1
        elif status == "wrong":
            counters["wrong"] += 1
        elif status == "unverifiable":
            counters["unverifiable"] += 1
        elif source == "calculated":
            counters["calculated"] += 1
        elif source == "manual":
            counters["manual"] += 1
        else:
            counters["extracted"] += 1

    # Most recent extraction timestamp (for staleness UI)
    latest: datetime | None = None
    for p in prov.values():
        if isinstance(p, dict):
            d = _parse_iso(p.get("extracted_at"))
            if d and (latest is None or d > latest):
                latest = d

    result = {"total_fields": total, **counters, "last_extracted_at": latest.isoformat() if latest else None}
    if verification:
        result["last_verified_at"] = verification.get("verified_at")
        result["confidence"] = verification.get("confidence")
    return result
