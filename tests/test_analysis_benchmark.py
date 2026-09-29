import json
from pathlib import Path
from scripts.evaluate_analysis import evaluate


def test_fixed_golden_cases_have_no_false_acceptance_or_headline_errors():
    cases = json.loads((Path(__file__).parent / "fixtures/analysis_golden.json").read_text())["cases"]
    report = evaluate(cases)
    assert report["case_count"] == 5
    assert report["false_acceptance"] == report["missed_expected"] == report["headline_errors"] == report["failed"] == 0, report["checks"]
