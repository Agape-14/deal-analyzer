"""Group-level source coverage, independent of material questions and scoring gates."""
from app.services.deal_scorer import SCORE_INPUT_GROUPS, category_inputs
from app.services.return_schedules import SCHEDULE_KEY, active_sources_fingerprint

GROUP_REVIEWS_KEY = "_review_group_coverage"
GROUP_LABELS = {
    "project_details": "Project details",
    "construction_budget": "Construction budget",
    "primary_return": "Primary return",
    "scoring_inputs": "Scoring inputs",
}
ACCEPTED_STATES = {"checked", "calculated", "manual"}


def source_reading(documents):
    """Preserve explicit reading failures without inferring completeness from omissions."""
    readings = []
    for document in documents:
        if not document.get("included_in_review", document.get("source_role", "active") == "active"):
            continue
        quality = document.get("extraction_quality") or document.get("reading") or {}
        issues = list(quality.get("warnings") or [])
        if quality.get("empty_pages"):
            issues.append("Some source pages have no readable text.")
        if quality.get("error"):
            issues.append("Document reading reported an error.")
        if quality.get("status") in {"queued", "extracting", "error"} or document.get("has_text") is False:
            status = "unread"
        elif issues:
            status = "partial"
        elif document.get("has_text") and quality.get("status") == "extracted":
            status = "read"
        else:
            status = "unknown"
        readings.append({"id": document["id"], "filename": document.get("filename", ""),
                         "status": status, "issues": issues})
    status = next((state for state in ("unread", "partial", "unknown")
                   if any(document["status"] == state for document in readings)), "read") if readings else "no_documents"
    return {"status": status, "documents": readings}


def build_review_coverage(metrics, facts, accepted, returns, schedule, documents, property_type="multifamily", reading_documents=None):
    readings = source_reading(documents if reading_documents is None else reading_documents)
    accepted_paths = {path for path, fact in facts.items()
                      if fact.get("value") is not None and fact.get("state") in ACCEPTED_STATES}
    reported_paths = {path for path, fact in facts.items()
                      if fact.get("value") is not None and fact.get("state") not in ACCEPTED_STATES}
    groups = []

    project = {path for path in accepted_paths if path.startswith("project_details.")}
    project_missing = []
    if property_type in {"multifamily", "mixed-use", "development"} and "project_details.unit_count" not in project:
        project_missing.append("Unit count")
    if not project - {"project_details.unit_count"}:
        project_missing.append("Project area, design, mix or timing")
    groups.append(("project_details", project, {path for path in reported_paths if path.startswith("project_details.")},
                   project_missing, "Review the source for project area, design, mix or timing."))

    totals = accepted_paths & {"deal_structure.total_project_cost", "construction_costs.total_project_cost"}
    components = {path for path in accepted_paths if path.startswith("construction_costs.")
                  and path != "construction_costs.total_project_cost"
                  and not path.endswith(("_per_unit", "_per_sqft"))}
    components |= accepted_paths & {"financial_projections.hard_costs", "financial_projections.soft_costs",
                                    "financial_projections.land_cost", "financial_projections.contingency"}
    hard_costs = components & {"construction_costs.hard_costs", "construction_costs.hard_costs_total",
                              "construction_costs.onsite_construction_costs", "financial_projections.hard_costs"}
    soft_costs = components & {"construction_costs.soft_costs", "construction_costs.soft_costs_total",
                              "construction_costs.preconstruction_soft_costs", "construction_costs.city_agency_fees",
                              "construction_costs.construction_leaseup_soft_costs", "financial_projections.soft_costs"}
    budget_missing = ([] if totals else ["Project cost"])
    if not hard_costs:
        budget_missing.append("Hard or on-site construction costs")
    if not soft_costs:
        budget_missing.append("Soft costs or project fees")
    budget_reported = {path for path in reported_paths if path.startswith("construction_costs.")
                       or path in {"financial_projections.hard_costs", "financial_projections.soft_costs",
                                   "financial_projections.land_cost", "financial_projections.contingency"}}
    groups.append(("construction_budget", totals | components, budget_reported, budget_missing,
                   "Review the source budget and its available cost components."))

    primary = {returns[key + "_path"] for key in ("target_irr", "target_equity_multiple", "cash_on_cash")
               if returns.get(key) is not None and returns.get(key + "_path")}
    if schedule and any(row.get("cash_on_cash_pct") is not None for row in schedule.get("rows", [])):
        primary.add(SCHEDULE_KEY)
    alternate = ".sale_scenario." if returns.get("primary_strategy", "").startswith("hold") else ".hold_scenario."
    primary_reported = {path for path in reported_paths if path.startswith("target_returns.") and alternate not in path}
    groups.append(("primary_return", primary, primary_reported, [] if primary else ["Primary return projection"],
                   "Review the primary-strategy projection and any annual return schedule."))

    scoring_paths, missing_categories = set(), []
    for category in ("returns", *SCORE_INPUT_GROUPS):
        supported, _ = category_inputs(accepted, category)
        scoring_paths.update(supported)
        if not supported:
            missing_categories.append(category.replace("_", " ").capitalize())
    groups.append(("scoring_inputs", scoring_paths, set(), missing_categories,
                   "Review the current sources for the remaining score categories."))

    source_fingerprint = active_sources_fingerprint(documents)
    assessments = metrics.get(GROUP_REVIEWS_KEY) or {}
    result = []
    for key, supported, reported, missing, action in groups:
        status = "available" if not missing else "partial" if supported else "needs_review"
        assessment = assessments.get(key) or {}
        current_assessment = assessment.get("sources_fingerprint") == source_fingerprint
        reviewed_reading = readings["status"] == "read" or (
            readings["status"] == "unknown" and reading_documents is None and assessment.get("reading_complete") is True)
        if missing and current_assessment and reviewed_reading and assessment.get("status") in {"not_stated", "not_applicable"}:
            status = assessment["status"]
            action = assessment["reason"]
        elif missing and readings["status"] in {"unread", "partial", "unknown", "no_documents"}:
            action = "Check document reading before reviewing the remaining group information."
        result.append({"key": key, "label": GROUP_LABELS[key], "status": status,
                       "accepted_paths": sorted(supported), "reported_paths": sorted(reported),
                       "missing": missing, "action": action if missing else ""})
    return {"sources": readings, "groups": result,
            "attention_count": sum(group["status"] in {"partial", "needs_review"} for group in result)}
