"""Read-only replay of every active deal in a private snapshot; no provider calls."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.analysis import build_analysis
from app.services.analysis_store import document_manifest
from app.services.cashflow_projector import project_cash_flows
from app.services.waterfall_calculator import waterfall_from_deal
from scripts.staging_snapshot import sha256


def json_value(value):
    return json.loads(value) if isinstance(value, str) else value or {}


def replay(snapshot):
    root = Path(snapshot).resolve()
    manifest = json.loads((root / "snapshot-manifest.json").read_text(encoding="utf-8"))
    if not manifest.get("complete") or sha256(root / "original.db") != manifest["database_sha256"]:
        raise ValueError("A complete, unchanged private snapshot is required.")
    for document in manifest["documents"]:
        path = (root / document["file"]).resolve()
        if not path.is_relative_to(root) or sha256(path) != document["sha256"]:
            raise ValueError("A copied original failed its integrity check.")
    reports = []
    with sqlite3.connect((root / "deal_analyzer.db").as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        for row in db.execute("SELECT * FROM deals ORDER BY id"):
            deal = dict(row)
            if deal.get("deleted_at"):
                continue
            documents = []
            for document in db.execute("SELECT * FROM deal_documents WHERE deal_id=? ORDER BY id", (deal["id"],)):
                doc = dict(document)
                doc["extraction_quality"] = json_value(doc.get("extraction_quality"))
                for name, default in {"source_role": "active", "superseded_by_id": None, "version_note": "", "file_sha256": "", "content_fingerprint": ""}.items():
                    doc.setdefault(name, default)
                documents.append(SimpleNamespace(**doc))
            metrics = json_value(deal.get("metrics"))
            candidate = build_analysis(metrics, document_manifest(documents), deal.get("property_type") or "multifamily")
            old = json_value(deal.get("analysis_snapshot"))
            reports.append({"id": deal["id"], "project_name": deal["project_name"],
                "before": {"stored_headlines": {k: deal.get(k) for k in ("target_irr", "target_equity_multiple", "target_cash_on_cash")}, "analysis_returns": old.get("returns")},
                "candidate": candidate,
                "cashflow": project_cash_flows(candidate["accepted_metrics"]),
                "waterfall": waterfall_from_deal(candidate["accepted_metrics"]),
                "critical_source_review": "pending: verify actual page/cell contents; a locator alone does not prove accuracy"})
    return {"scope": "all active deals", "deal_count": len(reports), "provider_calls": 0, "database_writes": 0,
            "factual_accuracy_verified": False, "deals": reports}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    args = parser.parse_args()
    report = replay(args.snapshot)
    output = Path(args.snapshot) / "replay-report.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Replayed {report['deal_count']} deals locally; private report: {output}. Source-content review is still required.")
