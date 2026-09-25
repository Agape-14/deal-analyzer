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

from app.services.canonical_metrics import canonical_return_summary, primary_strategy

SCHEMA_VERSION = 1
ACCEPTED = {"checked", "calculated", "manual"}
BAD = {"wrong", "missing", "unverifiable", "stale", "math_failed"}


class FactIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: str
    unit: Literal["currency", "percent", "multiple", "count", "years", "months", "text"]
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
    value: float | str | None = None
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
_register("deal_structure", "percent", "ltv loan_to_cost interest_rate preferred_return gp_equity_coinvest_pct permanent_interest_rate construction_interest_rate")
_register("deal_structure", "years", "hold_period_years investment_term_years amortization_years")
_register("deal_structure", "months", "loan_term_months construction_loan_term_months amortization_months")
_register("deal_structure", "text", "business_plan investment_strategy exit_strategies promote_structure waterfall_hurdle_basis preferred_return_allocation")
_register("project_details", "count", "unit_count total_sqft")
_register("project_details", "text", "unit_mix construction_type project_type")
_register("financial_projections", "currency", "stabilized_noi annual_debt_service avg_rent_per_unit revenue_per_unit hard_costs soft_costs land_cost contingency purchase_price")
_register("financial_projections", "percent", "entry_cap_rate exit_cap_rate occupancy_assumption rent_growth_assumption operating_expense_ratio")
_register("construction_costs", "currency", "hard_costs hard_costs_total soft_costs soft_costs_total land_cost land_cost_total contingency contingency_total total_project_cost hard_costs_per_unit soft_costs_per_unit land_cost_per_unit total_project_cost_per_unit hard_costs_per_sqft")
_register("construction_costs", "percent", "contingency_pct")
_register("underwriting_checks", "multiple", "dscr")
_register("underwriting_checks", "percent", "yield_on_cost")
_register("target_returns", "text", "primary_strategy")
_register("target_returns", "currency", "total_project_profit")
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


def input_fingerprint(metrics, documents, property_type):
    # Progress, counters and heuristic confidence do not create new facts.
    metrics = metrics if isinstance(metrics, dict) else {}
    keys = {k: v for k, v in metrics.items() if not k.startswith("_") and k != "validation_flags"}
    for key in ("_provenance", "_locks", "_fact_context", "_analysis_context", "_verified_document_set"):
        keys[key] = metrics.get(key)
    if isinstance(keys.get("_provenance"), dict):
        keys["_provenance"] = {p: {k: v for k, v in meta.items() if k not in {"confidence", "extracted_at", "verified_at"}} for p, meta in keys["_provenance"].items() if isinstance(meta, dict)}
    return digest(clean_json({"schema": SCHEMA_VERSION, "metrics": keys, "documents": documents, "property_type": property_type}))


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
    if unit == "percent":
        lower, upper = (-100, 1000) if path.endswith("irr") or path.endswith("rent_growth_assumption") else (0, 100)
        if not lower <= parsed <= upper:
            return None
    return parsed


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


def evidence_for(prov, documents):
    source = str(prov.get("verification_source") or prov.get("correction_source") or "")
    doc_id, name = prov.get("source_doc_id"), prov.get("source_doc_name")
    matches = [d for d in documents if (doc_id is not None and d["id"] == doc_id) or (name and d["filename"] == name) or (d["filename"] and d["filename"].lower() in source.lower())]
    if len(matches) != 1:
        return [], "The cited document is missing or ambiguous."
    doc = matches[0]
    stored_hash = prov.get("source_document_hash")
    if stored_hash and stored_hash != doc["content_hash"]:
        return [], "The source document changed after this fact was checked."
    page = prov.get("source_page")
    sheet, cell = prov.get("source_sheet"), prov.get("source_cell") or prov.get("source_range")
    locator = (isinstance(page, int) and not isinstance(page, bool) and page > 0 and (not doc.get("page_count") or page <= doc["page_count"])) or (isinstance(sheet, str) and bool(sheet.strip()) and isinstance(cell, str) and bool(cell.strip()))
    item = {"document_id": doc["id"], "document_name": doc["filename"], "content_hash": doc["content_hash"], "page": page, "sheet": sheet, "cell": cell, "excerpt": str(prov.get("source_excerpt") or source)[:1000]}
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
    facts = {}
    for path, values in flat.items():
        spec = REGISTRY.get(path)
        if not spec:
            continue
        unit, label = spec
        prov = provenance.get(path) if isinstance(provenance.get(path), dict) else {}
        context = contexts.get(path) if isinstance(contexts.get(path), dict) else {}
        value = values[0] if unit == "text" and isinstance(values[0], str) else valid_number(path, values[0], unit)
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
        elif status in BAD:
            fact.state, fact.reason = "disputed", str(prov.get("verification_note") or "The source check remains unresolved.")
        elif status == "manual":
            fact.state, fact.reason = "manual", "Analyst decision: " + str(prov.get("verification_note") or "Manually resolved; not an independent source check.")
        elif metrics.get("_verified_document_set") and metrics["_verified_document_set"] != digest(documents):
            fact.state, fact.reason = "reported", "The document package changed and is awaiting another source check."
        elif status == "confirmed" and not reason:
            fact.state = "checked"
        else:
            fact.reason = reason or "Reported value has not completed a source check."
        facts[path] = fact

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
        if prior and prior.state != "missing" and (not derived or prior.locked):
            continue
        inputs = [facts.get(p) for p in dependencies]
        if not all(f and f.state in ACCEPTED and isinstance(f.value, (float, int)) for f in inputs) or inputs[1].value <= 0:
            if prior and derived and not prior.locked:
                prior.state, prior.reason = "disputed", "A calculation input changed or is not accepted."
            continue
        # Don't combine debt or time-period contexts that explicitly disagree.
        if any(len({getattr(f.identity, dimension) for f in inputs if getattr(f.identity, dimension) != "unspecified"}) > 1 for dimension in ("debt_phase", "period", "currency")):
            if prior:
                prior.state, prior.reason = "disputed", "Calculation inputs refer to different phases or periods."
            continue
        unit, label = REGISTRY[path]
        facts[path] = Fact(path=path, label=label, identity=identity(path, unit, {}), value=round(inputs[0].value / inputs[1].value * scale, 2),
                           state="calculated", dependencies=dependencies, formula=formula,
                           evidence=[e for f in inputs for e in f.evidence])

    # Other historical derived values require a recorded dependency fingerprint.
    for path, fact in facts.items():
        if (provenance.get(path) or {}).get("source") == "calculated" and fact.state not in {"calculated", "manual"}:
            fact.state, fact.reason = "reported", "This calculation needs a supported formula and checked dependencies."

    accepted = {}
    for path, fact in facts.items():
        if fact.state in ACCEPTED:
            set_path(accepted, path, fact.value)
    strategy = primary_strategy(metrics)
    accepted.setdefault("target_returns", {})["primary_strategy"] = strategy
    selection = metrics.get("_analysis_context") or {}
    selected_class = selection.get("investor_class", "unspecified")
    classes = {f.identity.investor_class for p, f in facts.items() if p.startswith("target_returns.") and f.identity.investor_class != "unspecified"}
    ambiguous_class = len(classes) > 1 and selected_class not in classes
    for path, fact in facts.items():
        if not path.startswith("target_returns.") or fact.identity.unit == "text":
            continue
        scenario = fact.identity.scenario
        wrong_scenario = scenario != "unspecified" and scenario != ("hold" if strategy in {"hold", "hold_with_sale_option"} else strategy)
        wrong_class = ambiguous_class or (selected_class != "unspecified" and fact.identity.investor_class not in {selected_class})
        if wrong_scenario or wrong_class:
            set_path(accepted, path, None)
    returns = canonical_return_summary(accepted)
    if strategy == "unknown" or ambiguous_class:
        for key in ("target_irr", "target_equity_multiple", "cash_on_cash"):
            returns[key] = None
            returns[key + "_path"] = None

    required = {"deal_structure.total_project_cost", "deal_structure.total_equity_required", "deal_structure.debt_amount", "deal_structure.minimum_investment"}
    if property_type in {"multifamily", "mixed-use", "development"}:
        required.add("project_details.unit_count")
    if strategy == "sale":
        required.add("deal_structure.hold_period_years")
    material = required | {p for p in facts if p.startswith("target_returns.") and p.split(".")[-1] not in {"primary_strategy", "total_project_profit"}}
    # Optional alternate scenarios remain inspectable, not mandatory chores.
    material = {p for p in material if not (".sale_scenario." in p and strategy.startswith("hold")) and not (".hold_scenario." in p and strategy == "sale")}
    grouped = defaultdict(list)
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
    if ambiguous_class:
        grouped["Returns"].append({"path": "_analysis_context.investor_class", "reason": "Choose the investor class these returns should represent.", "state": "disputed"})
    if not any(returns.get(k) is not None for k in ("target_irr", "cash_on_cash", "target_equity_multiple")) and not grouped["Returns"]:
        grouped["Returns"].append({"path": "target_returns.target_irr", "reason": "No source-supported return is available for the primary strategy.", "state": "missing"})
    questions = [{"id": digest({"area": area, "issues": issues})[:16], "area": area, "title": f"Resolve {area.lower()}", "issues": issues,
                  "impact": "These facts are withheld from the accepted summary until the evidence or values are resolved."} for area, issues in sorted(grouped.items()) if issues]
    coverage = {"accepted": sum(f.state in ACCEPTED for f in facts.values()), "checked": sum(f.state == "checked" for f in facts.values()),
                "manual": sum(f.state == "manual" for f in facts.values()), "calculated": sum(f.state == "calculated" for f in facts.values()), "total": len(facts)}
    return clean_json({"schema_version": SCHEMA_VERSION, "input_hash": input_fingerprint(metrics, documents, property_type), "version": 0,
            "status": "questions" if questions else "ready", "primary_strategy": strategy, "investor_class": selected_class,
            "facts": {p: f.model_dump() for p, f in sorted(facts.items())}, "returns": returns, "accepted_metrics": accepted,
            "questions": questions, "coverage": coverage, "documents": documents,
            "unclassified_paths": sorted(p for p in flat if p not in REGISTRY)})


def analysis_for_deal(deal):
    stored = getattr(deal, "analysis_snapshot", None)
    if isinstance(stored, dict) and stored.get("schema_version") == SCHEMA_VERSION:
        return stored
    # A read-only preview for old rows. No automatic source rewrite or migration.
    return build_analysis(deal.metrics or {}, property_type=deal.property_type or "multifamily")


def effective_scores(deal):
    scores = copy.deepcopy(deal.scores or {})
    analysis = analysis_for_deal(deal)
    stale = scores.get("analysis_input_hash") != analysis["input_hash"]
    gate = dict(scores.get("data_quality") or {})
    can_score = bool(gate.get("can_score")) and not stale and not analysis["questions"]
    gate.update({"can_score": can_score, "analysis_version": analysis["version"], "stage": "outdated" if stale else analysis["status"]})
    if not can_score:
        scores["provisional_overall"] = scores.get("overall") or scores.get("provisional_overall")
        scores["overall"] = None
        for key in ("returns", "market", "structure", "risk", "financials", "underwriting", "sponsor"):
            if isinstance(scores.get(key), dict):
                scores[key] = {**scores[key], "score": None}
    scores["data_quality"] = gate
    return scores
