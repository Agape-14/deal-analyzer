"""Review coverage must describe omissions without withholding accepted facts."""
from types import SimpleNamespace

from app.services.analysis import analysis_for_deal, build_analysis, flatten
from app.services.review_coverage import GROUP_REVIEWS_KEY, build_review_coverage, source_reading
from app.services.return_schedules import active_sources_fingerprint


def reviewed_metrics():
    metrics = {
        "deal_structure": {"total_project_cost": 1000000, "total_equity_required": 400000,
                           "debt_amount": 600000, "minimum_investment": 25000, "ltv": 65},
        "project_details": {"unit_count": 10},
        "target_returns": {"primary_strategy": "hold", "hold_scenario": {"cash_on_cash_return": 8}},
    }
    metrics["_provenance"] = {path: {"status": "manual"} for path in flatten(metrics)}
    return metrics


def group(coverage, key):
    return next(row for row in coverage["groups"] if row["key"] == key)


def source():
    return {"id": 1, "filename": "Memo.pdf", "content_hash": "a", "included_in_review": True,
            "has_text": True, "extraction_quality": {"status": "extracted"}}


def test_group_gaps_are_visible_even_when_no_material_questions_remain():
    metrics = reviewed_metrics()
    analysis = build_analysis(metrics)
    coverage = analysis["review_coverage"]
    assert analysis["questions"] == []
    assert group(coverage, "project_details")["status"] == "partial"
    assert group(coverage, "construction_budget")["missing"] == ["Hard or on-site construction costs", "Soft costs or project fees"]
    assert group(coverage, "primary_return")["status"] == "available"
    assert group(coverage, "scoring_inputs")["status"] == "partial"
    assert "Market" in group(coverage, "scoring_inputs")["missing"]
    assert coverage["attention_count"] == 3
    assert analysis["returns"]["cash_on_cash"] == 8
    assert analysis["accepted_metrics"]["deal_structure"]["total_project_cost"] == 1000000


def test_read_documents_do_not_turn_missing_information_into_not_stated():
    metrics = reviewed_metrics()
    analysis = build_analysis(metrics, [source()])
    coverage = analysis["review_coverage"]
    assert coverage["sources"]["status"] == "read"
    assert group(coverage, "construction_budget")["status"] == "partial"
    assert group(coverage, "construction_budget")["status"] != "not_stated"


def test_readiness_checks_use_only_accepted_funding_budget_and_return_context():
    metrics = reviewed_metrics()
    return_path = "target_returns.hold_scenario.cash_on_cash_return"
    metrics["construction_costs"] = {
        "total_project_cost": 1_000_000, "land_cost_total": 100_000, "hard_costs_total": 580_000,
        "soft_costs_total": 220_000, "financing_costs": 100_000, "contingency_total": 40_000,
    }
    metrics["_provenance"].update({path: {"status": "manual"} for path in flatten(metrics)
                                   if path.startswith("construction_costs.")})
    metrics["_fact_context"] = {return_path: {"investor_class": "Class A", "basis": "net", "period": "Year 3"}}

    def checks(doc):
        readiness = build_analysis(metrics, [doc])["readiness"]
        return readiness, {check["key"]: check for check in readiness["checks"]}

    readiness, actual = checks(source())
    assert readiness["attention_count"] == 0
    assert all(check["status"] == "checked" for check in actual.values())
    assert "construction_costs.contingency_total" not in actual["budget"]["paths"]

    metrics["deal_structure"]["total_equity_required"] = 390_000
    metrics["construction_costs"]["total_project_cost"] = 980_000
    metrics["_fact_context"][return_path].pop("period")
    unread_page = source()
    unread_page["extraction_quality"]["empty_pages"] = [4]
    readiness, actual = checks(unread_page)
    assert readiness["attention_count"] == 4
    assert actual["sources"]["status"] == "incomplete"
    assert actual["budget"]["status"] == actual["funding"]["status"] == actual["returns"]["status"] == "attention"
    assert "return period" in actual["returns"]["detail"]
    assert "10,000" in actual["funding"]["detail"]


def test_refinance_balance_cannot_complete_funding_readiness():
    metrics = reviewed_metrics()
    debt_path = "deal_structure.debt_amount"
    metrics["_fact_context"] = {debt_path: {"debt_phase": "permanent"}}
    readiness = build_analysis(metrics, [source()])["readiness"]
    funding = next(check for check in readiness["checks"] if check["key"] == "funding")
    assert funding["status"] == "incomplete"
    assert funding["paths"] == [debt_path]


def test_approved_group_assessment_is_bound_to_sources_instead_of_metric_changes():
    metrics = reviewed_metrics()
    documents = [source()]
    metrics[GROUP_REVIEWS_KEY] = {"construction_budget": {
        "status": "not_stated", "reason": "The reviewed memo states no further construction budget components.",
        "sources_fingerprint": active_sources_fingerprint(documents), "reading_complete": True,
    }}
    assert group(build_analysis(metrics, documents)["review_coverage"], "construction_budget")["status"] == "not_stated"
    metrics["project_details"]["construction_type"] = "Wood frame"
    metrics["_provenance"]["project_details.construction_type"] = {"status": "manual"}
    assert group(build_analysis(metrics, documents)["review_coverage"], "construction_budget")["status"] == "not_stated"
    documents[0]["content_hash"] = "b"
    assert group(build_analysis(metrics, documents)["review_coverage"], "construction_budget")["status"] == "partial"
    assert metrics[GROUP_REVIEWS_KEY]["construction_budget"]["status"] == "not_stated"


def test_unread_partial_and_excluded_sources_have_distinct_reading_states():
    document = source()
    document["extraction_quality"].update(empty_pages=[2])
    assert source_reading([document])["status"] == "partial"
    document["extraction_quality"] = {"status": "error", "error": "Parser failed"}
    assert source_reading([document])["status"] == "unread"
    document["included_in_review"] = False
    assert source_reading([document])["status"] == "no_documents"
    assert source_reading([{"id": 2, "filename": "Legacy.pdf", "content_hash": "x"}])["status"] == "unknown"


def test_current_reading_warning_preserves_accepted_facts_and_requires_reading_review():
    metrics = reviewed_metrics()
    document = SimpleNamespace(id=1, filename="Memo.pdf", file_sha256="a", content_fingerprint="a",
        file_path="", doc_type="offering_memo", page_count=2, upload_date=None, extracted_text="Readable page",
        extraction_quality={"status": "extracted", "page_diagnostics": [{"page": 2, "image_text_unread": True}]})
    snapshot = build_analysis(metrics, [{"id": 1, "filename": "Memo.pdf", "content_hash": "a"}])
    deal = SimpleNamespace(metrics=metrics, property_type="multifamily", documents=[document], analysis_snapshot=snapshot)
    output = analysis_for_deal(deal)
    assert output["review_coverage"]["sources"]["status"] == "partial"
    assert output["facts"] == snapshot["facts"]
    assert output["returns"]["cash_on_cash"] == 8
    assert output["review_coverage"]["sources"]["documents"][0]["issues"]
    assert snapshot["review_coverage"]["sources"]["status"] == "unknown"


def test_a_checked_annual_schedule_counts_as_the_primary_projection():
    metrics = reviewed_metrics()
    del metrics["target_returns"]["hold_scenario"]
    analysis = build_analysis(metrics)
    coverage = build_review_coverage(metrics, analysis["facts"], analysis["accepted_metrics"], analysis["returns"],
        {"rows": [{"year": 1, "cash_on_cash_pct": 0}, {"year": 2, "cash_on_cash_pct": None}]}, [])
    assert analysis["returns"]["cash_on_cash"] is None
    assert group(coverage, "primary_return")["status"] == "available"
    assert group(coverage, "primary_return")["accepted_paths"] == ["_return_schedule"]


def test_source_failure_suspends_an_absence_assessment_without_erasing_it():
    metrics = reviewed_metrics()
    document = source()
    metrics[GROUP_REVIEWS_KEY] = {"construction_budget": {
        "status": "not_stated", "reason": "No component budget is stated in the reviewed source.",
        "sources_fingerprint": active_sources_fingerprint([document]), "reading_complete": True,
    }}
    document["extraction_quality"] = {"status": "error"}
    analysis = build_analysis(metrics, [document])
    assert group(analysis["review_coverage"], "construction_budget")["status"] == "partial"
    assert analysis["returns"]["cash_on_cash"] == 8
    assert metrics[GROUP_REVIEWS_KEY]["construction_budget"]["status"] == "not_stated"


def test_land_and_per_unit_values_do_not_hide_a_missing_construction_breakdown():
    metrics = reviewed_metrics()
    metrics["construction_costs"] = {"land_cost_total": 100000, "hard_costs_per_unit": 5000}
    for path in flatten(metrics):
        if path.startswith("construction_costs."):
            metrics["_provenance"][path] = {"status": "manual"}
    budget = group(build_analysis(metrics)["review_coverage"], "construction_budget")
    assert budget["status"] == "partial"
    assert budget["missing"] == ["Hard or on-site construction costs", "Soft costs or project fees"]
    metrics["construction_costs"].update(hard_costs_total=500000, soft_costs_total=100000)
    metrics["_provenance"]["construction_costs.hard_costs_total"] = {"status": "manual"}
    metrics["_provenance"]["construction_costs.soft_costs_total"] = {"status": "manual"}
    assert group(build_analysis(metrics)["review_coverage"], "construction_budget")["status"] == "available"


def test_group_absence_cannot_be_approved_from_an_unread_or_partial_source():
    from app.services.review_drafts import ReviewResult, coverage_rows
    document = SimpleNamespace(id=1, filename="Memo.pdf", file_sha256="a", content_fingerprint="a",
        file_path="", doc_type="offering_memo", page_count=2, upload_date=None, extracted_text="Readable page",
        extraction_quality={"status": "extracted", "empty_pages": [2]})
    result = ReviewResult(package_id="a" * 64, facts=[], coverage=[{
        "group": "construction_budget", "status": "not_stated", "reason": "No budget found after review.", "source_doc_ids": [1]}])
    assert "Read every active source completely" in coverage_rows([document], result)[0]["issue"]
    document.extraction_quality = {"status": "error"}
    assert coverage_rows([document], result)[0]["issue"]
    document.extraction_quality = {"status": "extracted", "page_diagnostics": [{"page": 2, "source": "ocr_weak"}]}
    assert "Read every active source completely" in coverage_rows([document], result)[0]["issue"]
    document.extraction_quality = {"status": "extracted"}
    assert coverage_rows([document], result)[0]["issue"] == ""
    document.extracted_text = "A1=Hard costs | B1=[formula has no cached value]"
    document.filename = "Budget.xlsx"
    assert "Read every active source completely" in coverage_rows([document], result)[0]["issue"]
