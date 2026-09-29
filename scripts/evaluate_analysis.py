"""Run a fixed, source-labeled analysis benchmark without a provider or database."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.analysis import build_analysis, ACCEPTED


def evaluate(cases):
    checks = []
    false_acceptance = missed_expected = headline_errors = 0
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
            checks.append({"case": case["id"], "kind": "fact", "field": path, "passed": passed, "expected": expected, "actual_state": actual.get("state")})
    return {"scope": "Fixed synthetic cases; not a measure of live extraction accuracy", "case_count": len(cases),
            "check_count": len(checks), "failed": sum(not check["passed"] for check in checks),
            "false_acceptance": false_acceptance, "missed_expected": missed_expected, "headline_errors": headline_errors, "checks": checks}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=Path(__file__).resolve().parents[1] / "tests/fixtures/analysis_golden.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(json.loads(args.cases.read_text())["cases"])
    if args.output:
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    raise SystemExit(bool(report["failed"]))
