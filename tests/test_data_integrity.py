"""Tests for the data-integrity primitives.

These functions are the backbone of the phase-6 guarantees: smart merge,
conflict detection, provenance tagging, locks, quality counters. Getting
any of these wrong corrupts the dashboard — they deserve coverage.
"""

from app.services.data_integrity import (
    detect_conflicts,
    mark_manual_edit,
    quality_summary,
    set_lock,
    smart_merge,
    stamp_verification,
    staleness_flags,
)


class _FakeDoc:
    def __init__(self, upload_date=None, filename="doc.pdf"):
        self.upload_date = upload_date
        self.filename = filename


# -------------------- smart_merge -------------------- #


def test_smart_merge_preserves_value_when_incoming_is_null():
    existing = {
        "deal_structure": {"ltv": 65, "debt_amount": 10_000_000},
        "target_returns": {"target_irr": 16},
    }
    incoming = {
        "deal_structure": {"ltv": None, "debt_amount": 12_000_000},
        "target_returns": {"target_irr": None},
    }
    merged, changes = smart_merge(existing, incoming, source_doc_id=1, source_doc_name="om.pdf")
    # LTV was null — old value survives
    assert merged["deal_structure"]["ltv"] == 65
    # Debt changed — new value wins
    assert merged["deal_structure"]["debt_amount"] == 12_000_000
    # IRR null — preserved
    assert merged["target_returns"]["target_irr"] == 16
    # Only debt_amount is in changes list
    assert "deal_structure.debt_amount" in changes
    assert "deal_structure.ltv" not in changes


def test_smart_merge_honors_manual_lock():
    existing = {
        "deal_structure": {"ltv": 65},
        "_locks": {"deal_structure.ltv": True},
    }
    incoming = {"deal_structure": {"ltv": 99}}
    merged, _ = smart_merge(existing, incoming)
    assert merged["deal_structure"]["ltv"] == 65  # lock wins even over non-null


def test_smart_merge_creates_provenance_per_field():
    merged, _ = smart_merge(
        {},
        {"deal_structure": {"ltv": 65}},
        source_doc_id=7,
        source_doc_name="om.pdf",
    )
    prov = merged["_provenance"]["deal_structure.ltv"]
    assert prov["source"] == "extraction"
    assert prov["source_doc_id"] == 7
    assert prov["source_doc_name"] == "om.pdf"
    assert prov["extracted_at"]  # non-empty ISO timestamp


# -------------------- detect_conflicts -------------------- #


def test_detect_conflicts_flags_cross_doc_disagreement():
    per_doc = [
        (1, "om.pdf", {"deal_structure": {"ltv": 65}}),
        (2, "proforma.pdf", {"deal_structure": {"ltv": 70}}),
        (3, "memo.pdf", {"deal_structure": {"ltv": 65}}),
    ]
    c = detect_conflicts(per_doc)
    assert "deal_structure.ltv" in c
    assert len(c["deal_structure.ltv"]) == 3


def test_detect_conflicts_ignores_small_numeric_drift():
    # 65.0 vs 65.01 is not a conflict (<2% relative diff)
    per_doc = [
        (1, "a", {"deal_structure": {"ltv": 65.0}}),
        (2, "b", {"deal_structure": {"ltv": 65.01}}),
    ]
    assert detect_conflicts(per_doc) == {}


def test_detect_conflicts_strings_must_match_exactly():
    per_doc = [
        (1, "a", {"market_location": {"submarket": "East Austin"}}),
        (2, "b", {"market_location": {"submarket": "east austin"}}),  # case diff = conflict
    ]
    c = detect_conflicts(per_doc)
    assert "market_location.submarket" in c


# -------------------- stamp_verification -------------------- #


def test_stamp_verification_adds_per_field_status():
    metrics = {"deal_structure": {"ltv": 65}}
    verification = {
        "summary": {"confidence_score": 88},
        "audit_results": [
            {
                "section": "deal_structure",
                "field": "ltv",
                "status": "confirmed",
                "source": "Page 3 confirms 65% LTV",
                "note": "Matches capital stack",
            }
        ],
    }
    out = stamp_verification(metrics, verification)
    prov = out["_provenance"]["deal_structure.ltv"]
    assert prov["status"] == "confirmed"
    assert prov["confidence"] == 88
    assert prov["source_page"] == 3
    assert out["_verification"]["confidence"] == 88
    assert out["_verification"]["totals"]["confirmed"] == 1


# -------------------- lock + manual edit -------------------- #


def test_set_lock_toggles_independently():
    metrics = {"deal_structure": {"ltv": 65}}
    metrics = set_lock(metrics, "deal_structure.ltv", True)
    assert metrics["_locks"]["deal_structure.ltv"] is True
    metrics = set_lock(metrics, "deal_structure.ltv", False)
    assert "deal_structure.ltv" not in (metrics.get("_locks") or {})


def test_mark_manual_edit_updates_and_locks():
    metrics = mark_manual_edit({}, "target_returns.target_irr", 15.5)
    assert metrics["target_returns"]["target_irr"] == 15.5
    assert metrics["_locks"]["target_returns.target_irr"] is True
    prov = metrics["_provenance"]["target_returns.target_irr"]
    assert prov["source"] == "manual"


# -------------------- quality_summary -------------------- #


def test_quality_summary_counts_every_category():
    metrics = {
        "_provenance": {
            "a.b": {"source": "extraction", "status": "confirmed"},
            "a.c": {"source": "extraction", "status": "extracted"},
            "a.d": {"source": "calculated", "status": "calculated"},
            "a.e": {"source": "manual", "status": "manual", "locked": True},
            "a.f": {"source": "extraction", "status": "extracted", "conflict": [{"doc_id": 1, "doc_name": "x", "value": 1}, {"doc_id": 2, "doc_name": "y", "value": 2}]},
            "a.g": {"source": "extraction", "status": "wrong"},
        }
    }
    q = quality_summary(metrics)
    assert q["total_fields"] == 6
    assert q["verified"] == 1
    assert q["extracted"] >= 1
    assert q["calculated"] == 1
    assert q["manual"] == 1
    assert q["conflicting"] == 1
    assert q["wrong"] == 1
    assert q["locked"] == 1


# -------------------- staleness -------------------- #


def test_staleness_flag_when_old_extraction():
    # Pretend the only extraction happened 120 days ago
    from datetime import datetime, timedelta, timezone

    long_ago = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    metrics = {"_provenance": {"a.b": {"extracted_at": long_ago}}}
    flags = staleness_flags(metrics, documents=[])
    assert any(f["category"] == "Staleness" for f in flags)


def test_staleness_flag_when_doc_newer_than_last_extraction():
    from datetime import datetime, timedelta, timezone

    ten_days_ago = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    metrics = {"_provenance": {"a.b": {"extracted_at": ten_days_ago}}}
    doc = _FakeDoc(upload_date=datetime.now(timezone.utc))
    flags = staleness_flags(metrics, documents=[doc])
    assert any("uploaded after" in f["message"] for f in flags)
