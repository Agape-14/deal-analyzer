import json
from pathlib import Path
from scripts.evaluate_analysis import evaluate
from scripts.evaluate_analysis import require_reviewed_sources
import pytest


def test_fixed_golden_cases_have_no_false_acceptance_or_headline_errors():
    cases = json.loads((Path(__file__).parent / "fixtures/analysis_golden.json").read_text())["cases"]
    report = evaluate(cases)
    assert report["case_count"] == 5
    assert report["false_acceptance"] == report["missed_expected"] == report["headline_errors"] == report["failed"] == 0, report["checks"]


def test_benchmark_detects_value_context_and_source_errors_independently():
    case = {"id": "independent-labels", "metrics": {}, "expected_returns": {},
            "expected_facts": {"deal_structure.minimum_investment": {"accepted": True, "value": 25000,
                               "identity": {"investor_class": "Class A"}, "evidence": [{"document_id": 1, "page": 2}]}}}
    report = evaluate([case])
    assert report["missing_required_facts"] == report["value_errors"] == report["context_errors"] == report["source_errors"] == 1
    assert report["failed"] == 1
    with pytest.raises(ValueError, match="approved real-document"):
        require_reviewed_sources([case])
