"""Run a fixed, source-labeled analysis benchmark without a provider or database."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.analysis import build_analysis, ACCEPTED


def evaluate(cases):
    checks = []
    false_acceptance = missed_expected = headline_errors = value_errors = context_errors = source_errors = 0
    for case in cases:
        analysis = build_analysis(case["metrics"], case.get("documents", []), case.get("property_type", "multifamily"))
        for key, expected in case["expected_returns"].items():
            actual = analysis["returns"][key]
            passed = actual == expected
            headline_errors += not passed
            checks.append({"case": case["id"], "kind": "headline", "field": key, "passed": passed, "expected": expected, "actual": actual})
        for path, expected in case.get("expected_facts", {}).items():
            actual = analysis["facts"].get(path, {})
            accepted = actual.get("state") in ACCEPTED
            false_acceptance += accepted and not expected["accepted"]
            missed_expected += expected["accepted"] and not accepted
            passed = accepted == expected["accepted"] and ("state" not in expected or actual.get("state") == expected["state"])
            if "value" in expected:
                correct = actual.get("value") == expected["value"]
                value_errors += not correct
                passed = passed and correct
            if "identity" in expected:
                correct = all(actual.get("identity", {}).get(key) == value for key, value in expected["identity"].items())
                context_errors += not correct
                passed = passed and correct
            if "evidence" in expected:
                correct = all(any(all(evidence.get(key) == value for key, value in wanted.items()) for evidence in actual.get("evidence", [])) for wanted in expected["evidence"])
                source_errors += not correct
                passed = passed and correct
            checks.append({"case": case["id"], "kind": "fact", "field": path, "passed": passed, "expected": expected, "actual_state": actual.get("state")})
    return {"scope": "Fixed synthetic cases; not a measure of live extraction accuracy", "case_count": len(cases),
            "check_count": len(checks), "failed": sum(not check["passed"] for check in checks),
            "false_acceptance": false_acceptance, "missed_expected": missed_expected, "missing_required_facts": missed_expected,
            "headline_errors": headline_errors, "value_errors": value_errors, "context_errors": context_errors, "source_errors": source_errors, "checks": checks}


def require_reviewed_sources(cases):
    """Validate label attestations; this cannot substitute for human review."""
    for case in cases:
        review = case.get("label_review", {})
        if not (review.get("status") == "approved" and review.get("reviewer") and review.get("reviewed_at") and review.get("real_document") is True and review.get("source_sha256")):
            raise ValueError(f"{case['id']}: approved real-document labels and source hashes are required")
        for path, expected in case.get("expected_facts", {}).items():
            if expected["accepted"] and not all(key in expected for key in ("value", "identity", "evidence")):
                raise ValueError(f"{case['id']} / {path}: independently reviewed value, context and source labels are required")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=Path(__file__).resolve().parents[1] / "tests/fixtures/analysis_golden.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--reviewed-real", action="store_true", help="Require independent source-label attestations; does not run extraction")
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text())["cases"]
    if args.reviewed_real:
        require_reviewed_sources(cases)
    report = evaluate(cases)
    if args.reviewed_real:
        report["scope"] = "Reviewed real-document analysis labels; saved extraction inputs, not a fresh provider extraction test"
    if args.output:
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    raise SystemExit(bool(report["failed"]))
