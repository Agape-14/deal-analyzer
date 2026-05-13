from app.services.extraction_accuracy import compare_field, evaluate_answer_key


def test_answer_key_matches_numeric_formats_and_tolerances():
    metrics = {
        "target_returns": {"target_irr": 17.02, "target_equity_multiple": 2.399},
        "deal_structure": {"minimum_investment": 252000},
    }
    answer_key = {
        "case_id": "capalina",
        "fields": [
            {"path": "target_returns.target_irr", "expected": "17.0%", "type": "pct", "tolerance": 0.1},
            {"path": "target_returns.target_equity_multiple", "expected": "2.40x", "type": "multiple"},
            {"path": "deal_structure.minimum_investment", "expected": "$252K", "type": "money"},
        ],
    }

    report = evaluate_answer_key(metrics, answer_key)

    assert report["passed"] is True
    assert report["accuracy"] == 100.0
    assert report["summary"]["matched"] == 3


def test_answer_key_flags_missing_and_mismatched_critical_fields():
    metrics = {
        "target_returns": {"target_irr": 13.0},
        "deal_structure": {},
    }
    answer_key = {
        "case_id": "bad_extract",
        "fields": [
            {"path": "target_returns.target_irr", "expected": 17.0, "type": "pct", "tolerance": 0.1},
            {"path": "deal_structure.minimum_investment", "expected": "$160K", "type": "money"},
            {"path": "deal_structure.optional_note", "required": False, "expected": None},
        ],
    }

    report = evaluate_answer_key(metrics, answer_key)

    assert report["passed"] is False
    assert report["accuracy"] == 0.0
    assert report["summary"]["mismatched"] == 1
    assert report["summary"]["missing"] == 1
    assert report["summary"]["skipped"] == 1
    assert {field["status"] for field in report["failed_fields"]} == {"mismatch", "missing"}


def test_answer_key_uses_aliases_and_reports_source_metadata():
    metrics = {
        "target_returns": {"net_irr": 0.13},
        "_provenance": {
            "target_returns.net_irr": {
                "status": "confirmed",
                "source_doc_name": "Model.xlsx",
                "source_page": 4,
            }
        },
    }
    field = {
        "path": "target_returns.target_irr",
        "aliases": ["target_returns.net_irr"],
        "expected": "13%",
        "type": "pct",
    }

    result = compare_field(metrics, field)

    assert result["status"] == "match"
    assert result["actual_path"] == "target_returns.net_irr"
    assert result["source_status"] == "confirmed"
    assert result["source"] == "Model.xlsx p.4"
