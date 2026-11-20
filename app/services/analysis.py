"""Deterministic, versioned facts and material questions. No provider calls.

Raw metrics remain the source/audit record. This module projects them into a
typed vocabulary; unknown fields never become accepted underwriting inputs.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.canonical_metrics import HOLD_CASH_YIELD_PATHS, canonical_return_summary, primary_strategy
from app.services.return_schedules import SCHEDULE_KEY, active_sources_fingerprint, project_return_schedule
from app.services.review_coverage import GROUP_REVIEWS_KEY, build_review_coverage
from app.services.review_findings import FINDINGS_KEY, project_findings
from app.services.review_readiness import review_readiness

SCHEMA_VERSION = 7
ACCEPTED = {"checked", "calculated", "manual"}
BAD = {"wrong", "missing", "unverifiable", "stale", "math_failed"}
RETURN_REVIEWS_KEY = "_return_reviews"
RETURN_CONTEXT_FIELDS = ("scenario", "investor_class", "basis", "period")


class FactIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: str
    unit: Literal["currency", "percent", "multiple", "count", "years", "months", "text", "waterfall_tiers"]
    scenario: str = "unspecified"
    investor_class: str = "unspecified"
    basis: str = "unspecified"
    debt_phase: str = "unspecified"
    period: str = "unspecified"
    currency: str = "unspecified"


class Fact(BaseModel):
    path: str
    label: str
    identity: FactIdentity
    value: float | str | list[dict[str, float]] | None = None
    state: Literal["reported", "checked", "calculated", "disputed", "missing", "manual", "unclassified"]
    reason: str = ""
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    formula: str | None = None
    locked: bool = False
    alternatives: list[Any] = Field(default_factory=list)


# Explicit vocabulary, including semantically distinct return and debt fields.
REGISTRY: dict[str, tuple[str, str]] = {}


def _register(section, unit, names):
    for name in names.split():
        REGISTRY[f"{section}.{name}"] = (unit, name.replace("_", " ").capitalize())


_register("deal_structure", "currency", "minimum_investment total_equity_required total_project_cost debt_amount preferred_equity_amount gp_cash_at_risk permanent_loan_amount construction_loan_amount")
_register("deal_structure", "percent", "ltv loan_to_cost interest_rate preferred_return gp_equity_coinvest_pct permanent_interest_rate construction_interest_rate fees_asset_mgmt fees_acquisition")
_register("deal_structure", "years", "hold_period_years investment_term_years amortization_years")
_register("deal_structure", "months", "loan_term_months construction_loan_term_months amortization_months")
_register("deal_structure", "text", "business_plan investment_strategy exit_strategies promote_structure waterfall_hurdle_basis preferred_return_allocation")
_register("deal_structure", "waterfall_tiers", "promote_tiers")
_register("project_details", "count", "unit_count total_sqft")
_register("project_details", "text", "unit_mix construction_type project_type entitlement_status construction_timeline construction_start completion_date expected_stabilization")
_register("financial_projections", "currency", "stabilized_noi annual_debt_service monthly_debt_service avg_rent_per_unit revenue_per_unit hard_costs soft_costs land_cost contingency purchase_price")
_register("financial_projections", "percent", "entry_cap_rate exit_cap_rate occupancy_assumption vacancy_assumption rent_growth_assumption operating_expense_ratio")
_register("construction_costs", "currency", "hard_costs hard_costs_total soft_costs soft_costs_total land_cost land_cost_total contingency contingency_total total_project_cost hard_costs_per_unit soft_costs_per_unit land_cost_per_unit total_project_cost_per_unit hard_costs_per_sqft")
_register("construction_costs", "percent", "contingency_pct")
_register("construction_costs", "currency", "preconstruction_soft_costs city_agency_fees offsite_development_costs onsite_construction_costs construction_leaseup_soft_costs financing_costs")
_register("financial_projections", "currency", "untrended_noi interest_only_debt_service amortizing_debt_service")
_register("underwriting_checks", "multiple", "dscr")
_register("underwriting_checks", "percent", "yield_on_cost break_even_occupancy")
_register("market_location", "percent", "market_rent_growth market_job_growth market_vacancy_rate")
_register("market_location", "count", "walk_score")
_register("sponsor_evaluation", "count", "sponsor_full_cycle_deals")
_register("target_returns", "text", "primary_strategy")
_register("target_returns", "currency", "total_project_profit")
_register("target_returns", "percent", "total_fee_drag")
for prefix in ("target_returns", "target_returns.hold_scenario", "target_returns.sale_scenario"):
    _register(prefix, "percent", "target_irr net_irr gross_irr sale_irr target_cash_on_cash cash_on_cash_return distribution_yield")
    _register(prefix, "multiple", "target_equity_multiple net_equity_multiple gross_equity_multiple sale_equity_multiple")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def clean_json(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    return value


def input_fingerprint(metrics, documents, property_type, *, schema_version=None):
    # Progress, counters and heuristic confidence do not create new facts.
    metrics = metrics if isinstance(metrics, dict) else {}
    keys = {k: v for k, v in metrics.items() if not k.startswith("_") and k != "validation_flags"}
    for key in ("_provenance", "_locks", "_fact_context", "_analysis_context", "_verified_document_set"):
        keys[key] = metrics.get(key)
    for key in (SCHEDULE_KEY, "_financing_measures", RETURN_REVIEWS_KEY, GROUP_REVIEWS_KEY):
        if key in metrics:
            keys[key] = metrics[key]
    for key in (FINDINGS_KEY, "_return_crosscheck"):
        if key in metrics:
            keys[key] = metrics[key]
    if isinstance(keys.get("_provenance"), dict):
        keys["_provenance"] = {p: {k: v for k, v in meta.items() if k not in {"confidence", "extracted_at", "verified_at"}} for p, meta in keys["_provenance"].items() if isinstance(meta, dict)}
    return digest(clean_json({"schema": SCHEMA_VERSION if schema_version is None else schema_version,
                              "metrics": keys, "documents": documents, "property_type": property_type}))


def flatten(metrics):
    """Collect nested/dotted aliases without silently choosing a winner."""
    result = defaultdict(list)
    def walk(value, prefix):
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{prefix}.{key}" if prefix else key)
        else:
            result[prefix].append(value)
    for section, block in metrics.items():
        if not section.startswith("_") and section != "validation_flags":
            walk(block, section)
    return result


def set_path(tree, path, value):
    parts = path.split(".")
    for part in parts[:-1]:
        if not isinstance(tree.get(part), dict):
            tree[part] = {}
        tree = tree[part]
    tree[parts[-1]] = value


def number(value, unit):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", "")
        # Do not reinterpret fractions as percent, or parse ranges as points.
        if unit == "percent":
            value = value.removesuffix("%").strip()
        elif unit == "multiple":
            value = value.removesuffix("x").strip()
        elif unit == "currency":
            value = value.removeprefix("$").strip()
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def valid_number(path, value, unit):
    parsed = number(value, unit)
    if parsed is None:
        return None
    if unit in {"currency", "count", "multiple", "years", "months"} and parsed < 0:
        return None
    if unit == "count" and not parsed.is_integer():
        return None
    if path == "market_location.walk_score" and parsed > 100:
        return None
    if unit == "percent":
        lower, upper = (-100, 1000) if path.endswith(("irr", "rent_growth_assumption", "market_rent_growth", "market_job_growth")) else (0, 100)
        if not lower <= parsed <= upper:
            return None
    return parsed


def valid_tiers(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        return None
    result, previous = [], -1
    for tier in value:
        if not isinstance(tier, dict) or set(tier) != {"threshold", "lp_split", "gp_split"}:
            return None
        parsed = {key: number(tier[key], "percent") for key in tier}
        if any(v is None or v < 0 or v > 100 for v in parsed.values()):
            return None
        if parsed["threshold"] < previous or abs(parsed["lp_split"] + parsed["gp_split"] - 100) > .01:
            return None
        previous = parsed["threshold"]
        result.append(parsed)
    return result


def identity(path, unit, context):
    key = path.split(".")[-1]
    scenario = "hold" if ".hold_scenario." in path else "sale" if ".sale_scenario." in path else "unspecified"
    basis = "net" if key.startswith("net_") else "gross" if key.startswith("gross_") else "unspecified"
    metric = "irr" if key.endswith("irr") else "equity_multiple" if "equity_multiple" in key else "cash_on_cash" if "cash_on_cash" in key else key
    defaults = {"scenario": scenario, "basis": basis}
    if "permanent_" in key:
        defaults["debt_phase"] = "permanent"
    if "construction_loan" in key or "construction_interest" in key:
        defaults["debt_phase"] = "construction"
    # Context can narrow an ambiguous path, never relabel a specifically named one.
    for dim in ("scenario", "investor_class", "basis", "debt_phase", "period", "currency"):
        if isinstance(context.get(dim), str) and context[dim].strip() and defaults.get(dim, "unspecified") == "unspecified":
            defaults[dim] = context[dim].strip()[:100]
    return FactIdentity(metric=metric, unit=unit, **defaults)


def return_review_binding(metrics, path, value):
    return digest(clean_json([value, (metrics.get("_provenance") or {}).get(path),
                              (metrics.get("_fact_context") or {}).get(path)]))


def apply_return_review(fact, record, metrics, context, documents, active_sources):
    if not isinstance(record, dict) or record.get("binding") != return_review_binding(metrics, fact.path, fact.value):
        return
    if record.get("action") == "withhold":
        fact.state = "disputed"
        fact.reason = "Analyst withheld this return: " + record["reason"]
    elif record.get("action") == "scope" and record.get("document_set") == active_sources:
        evidence, issue = evidence_for(record["citation"], documents)
        if not issue:
            reviewed_context = {**context, **record["context"]}
            fact.identity = identity(fact.path, fact.identity.unit, reviewed_context)
            for item in evidence:
                if item not in fact.evidence:
                    fact.evidence.append(item)
            return reviewed_context
    return None


def evidence_for(prov, documents):
    source = str(prov.get("verification_source") or prov.get("correction_source") or "")
    doc_id, name = prov.get("source_doc_id"), prov.get("source_doc_name")
    # An exact document ID is authoritative; a same-named file cannot obscure it.
    if doc_id is not None:
        matches = [d for d in documents if d["id"] == doc_id]
    elif name:
        matches = [d for d in documents if d["filename"].casefold() == str(name).casefold()]
    else:
        matches = [d for d in documents if d["filename"] and d["filename"].lower() in source.lower()]
    if len(matches) > 1 and all(d.get("file_sha256") for d in matches) and len({d["file_sha256"] for d in matches}) == 1:
        matches = sorted(matches, key=lambda d: (d.get("source_role", "active") != "active", d["id"]))[:1]
    if len(matches) != 1:
        return [], "The cited document is missing or ambiguous."
    doc = matches[0]
    if doc.get("source_role", "active") != "active":
        return [], "The cited document is superseded or belongs to an alternate scenario. Use a current primary source."
    stored_hash = prov.get("source_document_hash")
    if stored_hash and stored_hash != doc["content_hash"]:
        return [], "The source document changed after this fact was checked."
    page = prov.get("source_page")
    sheet, cell = prov.get("source_sheet"), prov.get("source_cell") or prov.get("source_range")
    locator = (isinstance(page, int) and not isinstance(page, bool) and page > 0 and (not doc.get("page_count") or page <= doc["page_count"])) or (isinstance(sheet, str) and bool(sheet.strip()) and isinstance(cell, str) and bool(cell.strip()))
    item = {"document_id": doc["id"], "document_name": doc["filename"], "content_hash": doc["content_hash"], "page": page, "sheet": sheet, "cell": cell, "excerpt": str(prov.get("source_excerpt") or source)[:1000]}
    if page and prov.get("source_table_index"):
        item.update({"table_index": prov["source_table_index"], "table_row": prov.get("source_table_row"),
                     "table_column": prov.get("source_table_column"), "column_label": prov.get("source_column_label")})
    return [item], "" if locator else "A page or spreadsheet cell citation is needed."


def group_for(path):
    if path.startswith("target_returns"):
        return "Returns"
    if any(token in path for token in ("debt", "loan", "ltv", "dscr", "interest_rate")):
        return "Debt"
    if path.startswith("construction_costs"):
        return "Construction"
    if path.startswith("deal_structure"):
        return "Capital and terms"
    return "Property and operations"


def build_analysis(metrics, documents=None, property_type="multifamily"):
    metrics = copy.deepcopy(metrics) if isinstance(metrics, dict) else {}
    documents = documents or []
    flat = flatten(metrics)
    provenance = metrics.get("_provenance") or {}
    contexts = metrics.get("_fact_context") or {}
    return_reviews = metrics.get(RETURN_REVIEWS_KEY) or {}
    active_sources = active_sources_fingerprint(documents) if return_reviews else None
    reviewed_contexts = {}
    facts = {}
    reconciliation = []
    current_document_set = digest(documents)
    for path, values in flat.items():
        spec = REGISTRY.get(path)
        if not spec:
            continue
        unit, label = spec
        prov = provenance.get(path) if isinstance(provenance.get(path), dict) else {}
        context = contexts.get(path) if isinstance(contexts.get(path), dict) else {}
        value = (values[0] if isinstance(values[0], str) else None) if unit == "text" else valid_tiers(values[0]) if unit == "waterfall_tiers" else valid_number(path, values[0], unit)
        fact = Fact(path=path, label=label, identity=identity(path, unit, context), value=value,
                    state="reported", locked=bool(prov.get("locked") or (metrics.get("_locks") or {}).get(path)),
                    dependencies=[p for p in prov.get("dependencies", []) if isinstance(p, str)])
        fact.evidence, reason = evidence_for(prov, documents)
        status = str(prov.get("status") or "").lower()
        if value is None:
            fact.state, fact.reason = "missing", "No valid value with the expected unit is available."
        elif len({json.dumps(clean_json(v), sort_keys=True) for v in values}) > 1 or prov.get("conflict"):
            fact.state, fact.reason = "disputed", "The same fact has conflicting source values."
            fact.alternatives = clean_json(prov.get("conflict") or values)
        elif prov.get("source_challenge"):
            fact.state, fact.reason = "disputed", str(prov["source_challenge"])
        elif status in BAD:
            fact.state, fact.reason = "disputed", str(prov.get("verification_note") or "The source check remains unresolved.")
        elif status == "manual":
            fact.state, fact.reason = "manual", "Analyst decision: " + str(prov.get("verification_note") or "Manually resolved; not an independent source check.")
            if prov.get("source_value_note"):
                fact.reason += " " + str(prov["source_value_note"])
        elif (source_set := prov.get("review_document_set") or metrics.get("_verified_document_set")) and source_set != current_document_set:
            fact.state, fact.reason = "reported", "The document package changed and is awaiting another source check."
        elif status == "confirmed" and prov.get("source_check_version") != 1:
            fact.reason = "This older confirmation needs a fresh check of the quoted source text."
        elif status == "confirmed" and not reason:
            fact.state = "checked"
            fact.reason = str(prov.get("source_value_note") or "")
        else:
            fact.reason = reason or "Reported value has not completed a source check."
        if fact.state in ACCEPTED and path in return_reviews:
            reviewed_context = apply_return_review(fact, return_reviews[path], metrics, context, documents, active_sources)
            if reviewed_context is not None:
                reviewed_contexts[path] = reviewed_context
        facts[path] = fact

    funding_paths = ["deal_structure.debt_amount", "deal_structure.total_equity_required", "deal_structure.total_project_cost"]
    funding = [facts.get(p) for p in funding_paths]
    if all(f and f.state in ACCEPTED for f in funding):
        dimensions = ("debt_phase", "period", "currency")
        incompatible = any(len({getattr(f.identity, dim) for f in funding if getattr(f.identity, dim) != "unspecified"}) > 1 for dim in dimensions)
        gap = funding[0].value + funding[1].value - funding[2].value
        if incompatible or abs(gap) > max(1000, funding[2].value * .01):
            reason = ("Debt, equity and project cost refer to different phases, periods or currencies. Resolve their context before reconciling funding." if incompatible else
                      f"Debt plus equity differs from total project cost by {gap:,.0f}. Check the funding amounts or provide the missing source/use; accepting a source value does not resolve this calculation.")
            reconciliation.extend({"path": path, "area": "Debt", "state": "disputed", "reason": reason} for path in funding_paths)

    # Preserve an explicit source figure when a one-input conversion is available.
    direct_formulas = (
        ("financial_projections.annual_debt_service", "financial_projections.monthly_debt_service", 12, 0, "Monthly debt service × 12"),
        ("financial_projections.occupancy_assumption", "financial_projections.vacancy_assumption", -1, 100, "100 − vacancy assumption"),
    )
    for path, source_path, scale, offset, formula in direct_formulas:
        source = facts.get(source_path)
        prior = facts.get(path)
        derived = (provenance.get(path) or {}).get("source") == "calculated" and (provenance.get(path) or {}).get("dependencies") == [source_path]
        if not source or source.state not in ACCEPTED or not isinstance(source.value, (float, int)):
            continue
        if prior and prior.value is not None and not derived:
            continue
        context = {key: getattr(source.identity, key) for key in ("period", "debt_phase", "currency")}
        if path.endswith("annual_debt_service") and context["period"].casefold() in {"monthly", "per month"}:
            context["period"] = "annual"
        unit, label = REGISTRY[path]
        facts[path] = Fact(path=path, label=label, identity=identity(path, unit, context),
            value=round(source.value * scale + offset, 2), state="calculated", formula=formula,
            dependencies=[source_path], evidence=source.evidence)
        reviewed_contexts[path] = context

    # Recalculate supported formulas from accepted dependencies on every revision.
    # A manually resolved/reported source figure is never overwritten by a formula.
    formulas = [
        ("deal_structure.loan_to_cost", ["deal_structure.debt_amount", "deal_structure.total_project_cost"], 100, "Debt / cost × 100"),
        ("underwriting_checks.yield_on_cost", ["financial_projections.stabilized_noi", "deal_structure.total_project_cost"], 100, "NOI / cost × 100"),
        ("underwriting_checks.dscr", ["financial_projections.stabilized_noi", "financial_projections.annual_debt_service"], 1, "NOI / annual debt service"),
    ]
    for path, dependencies, scale, formula in formulas:
        prior = facts.get(path)
        derived = (provenance.get(path) or {}).get("source") == "calculated"
        inputs = [facts.get(p) for p in dependencies]
        if not all(f and f.state in ACCEPTED and isinstance(f.value, (float, int)) for f in inputs) or inputs[1].value <= 0:
            if prior and derived and not prior.locked:
                prior.state, prior.reason = "disputed", "A calculation input changed or is not accepted."
            continue
        if prior and prior.state in ACCEPTED and any(
            getattr(prior.identity, dimension) != "unspecified" and any(
                getattr(value.identity, dimension) not in {"unspecified", getattr(prior.identity, dimension)} for value in inputs)
            for dimension in ("debt_phase", "period", "currency")
        ):
            # A quoted ratio from another dated phase has its own source basis.
            continue
        # Don't combine debt or time-period contexts that explicitly disagree.
        if any(len({getattr(f.identity, dimension) for f in inputs if getattr(f.identity, dimension) != "unspecified"}) > 1 for dimension in ("debt_phase", "period", "currency")):
            if prior:
                prior.state, prior.reason = "disputed", "Calculation inputs refer to different phases or periods."
            continue
        unit, label = REGISTRY[path]
        calculated = round(inputs[0].value / inputs[1].value * scale, 2)
        if prior and prior.state != "missing" and (not derived or prior.locked):
            if prior.state in ACCEPTED and abs(prior.value - calculated) > max(.02, abs(calculated) * .02):
                prior.state, prior.reason = "disputed", f"Reported {prior.value} disagrees with {formula} = {calculated}. Resolve the inputs or the reported value."
                prior.dependencies, prior.formula = dependencies, formula
                reconciliation.append({"path": path, "state": "disputed", "reason": prior.reason})
            continue
        formula_context = {dimension: next((getattr(value.identity, dimension) for value in inputs
                                           if getattr(value.identity, dimension) != "unspecified"), "unspecified")
                           for dimension in ("debt_phase", "period", "currency")}
        facts[path] = Fact(path=path, label=label, identity=identity(path, unit, formula_context), value=calculated,
                           state="calculated", dependencies=dependencies, formula=formula,
                           evidence=[e for f in inputs for e in f.evidence])
        reviewed_contexts[path] = formula_context

    # Other historical derived values require a recorded dependency fingerprint.
    for path, fact in facts.items():
        if (provenance.get(path) or {}).get("source") == "calculated" and fact.state not in {"calculated", "manual"}:
            fact.state, fact.reason = "reported", "This calculation needs a supported formula and checked dependencies."

    accepted = {}
    for path, fact in facts.items():
        if fact.state in ACCEPTED:
            set_path(accepted, path, fact.value)
    from app.services.model_limits import model_limits
    accepted["_model_limits"] = model_limits(metrics)
    strategy = primary_strategy(metrics)
    accepted.setdefault("target_returns", {})["primary_strategy"] = strategy
    accepted["_fact_context"] = {**contexts, **reviewed_contexts}
    selection = metrics.get("_analysis_context") or {}
    selected_class = selection.get("investor_class")
    if not isinstance(selected_class, str) or not selected_class.strip():
        selected_class = "unspecified"
    hold_strategy = strategy in {"hold", "hold_with_sale_option"}
    schedule = project_return_schedule(metrics, documents) if hold_strategy else None
    if schedule and selected_class != "unspecified" and selected_class.casefold() != schedule["investor_class"].casefold():
        schedule = None
    scenario = "hold" if hold_strategy else strategy
    returns_for_scenario = [fact for path, fact in facts.items()
                            if path.startswith("target_returns.") and fact.identity.unit in {"percent", "multiple"}
                            and fact.state in ACCEPTED and fact.identity.scenario in {"unspecified", scenario}]
    classes = {fact.identity.investor_class for fact in returns_for_scenario if fact.identity.investor_class != "unspecified"}
    ambiguous_class = len(classes) > 1 and selected_class not in classes
    for path, fact in facts.items():
        if not path.startswith("target_returns.") or fact.identity.unit == "text":
            continue
        wrong_scenario = fact.identity.scenario not in {"unspecified", scenario}
        wrong_class = ambiguous_class or (selected_class != "unspecified" and fact.identity.investor_class not in {selected_class})
        superseded_yield = schedule is not None and fact.identity.metric in {"cash_on_cash", "distribution_yield"}
        if wrong_scenario or wrong_class or superseded_yield:
            set_path(accepted, path, None)
    returns = canonical_return_summary(accepted)
    if strategy == "unknown" or ambiguous_class:
        for key in ("target_irr", "target_equity_multiple", "cash_on_cash"):
            returns[key] = None
            returns[key + "_path"] = None
    if schedule:
        # A reviewed series supplies the hold projection without selecting one year as the headline.
        returns["cash_on_cash"] = None
        returns["cash_on_cash_path"] = None

    required = {"deal_structure.total_project_cost", "deal_structure.total_equity_required", "deal_structure.debt_amount", "deal_structure.minimum_investment"}
    if property_type in {"multifamily", "mixed-use", "development"}:
        required.add("project_details.unit_count")
    if strategy == "sale":
        required.add("deal_structure.hold_period_years")
    material = required | {p for p in facts if p.startswith("target_returns.") and p.split(".")[-1] not in {"primary_strategy", "total_project_profit"}}
    # Optional alternate scenarios remain inspectable, not mandatory chores.
    material = {p for p in material if not (".sale_scenario." in p and strategy.startswith("hold")) and not (".hold_scenario." in p and strategy == "sale")}
    if hold_strategy:
        # A hold summary needs a cash yield, not every historic IRR/multiple
        # alias or an optional exit calculation. Keep those facts in Analysis.
        material = {p for p in material if not p.startswith("target_returns.")}
        if returns.get("cash_on_cash") is None and not schedule:
            material.add(next((p for p in HOLD_CASH_YIELD_PATHS if p in facts and facts[p].value is not None),
                              HOLD_CASH_YIELD_PATHS[0]))
    grouped = defaultdict(list)
    for issue in reconciliation:
        grouped[issue.get("area", group_for(issue["path"]))].append({k: v for k, v in issue.items() if k != "area"})
    for path in sorted(material):
        fact = facts.get(path)
        if fact and fact.state in ACCEPTED:
            continue
        if not fact:
            unit, label = REGISTRY[path]
            fact = Fact(path=path, label=label, identity=identity(path, unit, {}), state="missing", reason="Not found in the reviewed documents.")
            facts[path] = fact
        grouped[group_for(path)].append({"path": path, "reason": fact.reason, "state": fact.state})
    if strategy == "unknown":
        grouped["Returns"].append({"path": "target_returns.primary_strategy", "reason": "Identify whether the primary strategy is hold or sale before comparing returns.", "state": "missing"})
    if ambiguous_class and not schedule:
        grouped["Returns"].append({"path": "_analysis_context.investor_class", "reason": "Choose the investor class these returns should represent.", "state": "disputed"})
    if not schedule and not any(returns.get(k) is not None for k in ("target_irr", "cash_on_cash", "target_equity_multiple")) and not grouped["Returns"]:
        grouped["Returns"].append({"path": "target_returns.target_irr", "reason": "No source-supported return is available for the primary strategy.", "state": "missing"})
    questions = [{"id": digest({"area": area, "issues": issues})[:16], "area": area, "title": f"Resolve {area.lower()}", "issues": issues,
                  "impact": "The summary remains incomplete until these evidence or calculation questions are resolved."} for area, issues in sorted(grouped.items()) if issues]
    coverage = {"accepted": sum(f.state in ACCEPTED for f in facts.values()), "checked": sum(f.state == "checked" for f in facts.values()),
                "manual": sum(f.state == "manual" for f in facts.values()), "calculated": sum(f.state == "calculated" for f in facts.values()), "total": len(facts)}
    from app.services.financing_measures import project_financing

    financing = project_financing(metrics, documents, (accepted.get("deal_structure") or {}).get("debt_amount"))
    serialized_facts = {p: f.model_dump() for p, f in sorted(facts.items())}
    review_coverage = build_review_coverage(metrics, serialized_facts, accepted, returns, schedule, documents, property_type)
    from app.services.return_crosscheck import project_return_crosscheck

    analysis = {"schema_version": SCHEMA_VERSION, "input_hash": input_fingerprint(metrics, documents, property_type), "version": 0,
            "status": "questions" if questions else "ready", "primary_strategy": strategy, "investor_class": selected_class,
            "facts": serialized_facts, "returns": returns, "accepted_metrics": accepted,
            "return_schedule": schedule, "financing": financing,
            "findings": project_findings(metrics, documents),
            "return_crosscheck": project_return_crosscheck(metrics, documents),
            "questions": questions, "coverage": coverage, "review_coverage": review_coverage, "documents": documents,
            "unclassified_paths": sorted(p for p in flat if p not in REGISTRY)}
    analysis["readiness"] = review_readiness(analysis)
    return clean_json(analysis)


def analysis_for_deal(deal, *, reading_documents=None):
    stored = getattr(deal, "analysis_snapshot", None)
    if isinstance(stored, dict) and stored.get("schema_version") == SCHEMA_VERSION:
        preview = copy.deepcopy(stored)
    else:
        # Rebuild an older snapshot with its recorded document manifest and revision.
        documents = (stored or {}).get("documents", []) if isinstance(stored, dict) else []
        preview = build_analysis(deal.metrics or {}, documents, property_type=deal.property_type or "multifamily")
        if isinstance(stored, dict):
            preview["version"] = stored.get("version", 0)
            if stored.get("created_at"):
                preview["created_at"] = stored["created_at"]
    if reading_documents is None and "documents" in deal.__dict__:
        from app.services.document_versions import document_payloads
        reading_documents = document_payloads(deal.__dict__["documents"])
    preview["review_coverage"] = build_review_coverage(deal.metrics or {}, preview["facts"],
        preview["accepted_metrics"], preview["returns"], preview.get("return_schedule"), preview["documents"],
        deal.property_type or "multifamily", reading_documents)
    preview["readiness"] = review_readiness(preview)
    preview.setdefault("findings", [])
    preview.setdefault("return_crosscheck", None)
    return preview


def effective_scores(deal):
    scores = copy.deepcopy(deal.scores or {})
    analysis = analysis_for_deal(deal)
    stale = (scores.get("analysis_input_hash") != analysis["input_hash"]
             or scores.get("input_policy") != "accepted-facts-v1"
             or scores.get("score_policy") != "observed-categories-v1")
    if stale:
        scores = score_accepted_deal(deal, deal.metrics or {})
    gate = dict(scores.get("data_quality") or {})
    gate["analysis_version"] = analysis["version"]
    scores["data_quality"] = gate
    from app.services.score_comparison import comparison_basis

    scores["comparison_basis"] = comparison_basis(scores, analysis["facts"])
    return scores


def score_accepted_deal(deal, metrics):
    """All score categories consume the same typed inputs as the summary.

    Raw data is retained for audit, but unknown fields, optional source claims
    and incompatible return contexts cannot silently influence scoring.
    """
    from app.services.analysis_store import document_manifest
    from app.services.deal_scorer import score_deal
    from app.services.math_checker import run_math_checks

    documents = (document_manifest(deal.__dict__["documents"]) if "documents" in deal.__dict__
                 else (getattr(deal, "analysis_snapshot", None) or {}).get("documents", []))
    analysis = build_analysis(metrics, documents, deal.property_type)
    inputs = copy.deepcopy(analysis["accepted_metrics"])
    inputs["_provenance"] = {
        path: copy.deepcopy((metrics.get("_provenance") or {}).get(path) or {})
        for path, fact in analysis["facts"].items() if fact["state"] in ACCEPTED
    }
    inputs["_verification"] = copy.deepcopy(metrics.get("_verification") or {})
    scores = score_deal(inputs, math_checks=run_math_checks(inputs))
    scores["input_policy"] = "accepted-facts-v1"
    scores["analysis_input_hash"] = analysis["input_hash"]
    complete = scores["coverage"]["supported_categories"] == scores["coverage"]["total_categories"]
    can_score = complete and not analysis["questions"] and scores["data_quality"]["math_summary"]["fail"] == 0
    scores["overall"] = scores["provisional_overall"] if can_score else None
    scores["data_quality"].update({"can_score": can_score, "analysis_version": analysis["version"],
                                    "stage": "ready" if can_score else "partial",
                                    "category_scores_available": scores["coverage"]["supported_categories"] > 0})
    return scores
