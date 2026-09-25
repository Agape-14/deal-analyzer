"""Retain model limitations even when unsupported source fields are withheld."""
import re


def model_limits(metrics):
    entries = []
    def walk(value, path=""):
        if isinstance(value, dict):
            for key, child in value.items():
                if not key.startswith("_"):
                    walk(child, f"{path}.{key}")
        elif isinstance(value, list):
            for child in value:
                walk(child, path)
        elif value not in (None, "", False, 0):
            entries.append((path.lower(), str(value).lower()))
    for section in ("deal_structure", "target_returns", "financial_projections", "project_details"):
        walk(metrics.get(section), section)
    text = " ".join(path + " " + value for path, value in entries)
    cashflow, waterfall = [], []
    if re.search(r"refinanc|cash.out|cash_out", text):
        cashflow.append("Refinancing or cash-out terms require a dated debt and proceeds schedule.")
        waterfall.append("Refinancing distributions require dated capital balances and allocation rules.")
    if any("amortiz" in path for path, _ in entries):
        cashflow.append("Amortizing debt requires its payment and remaining-balance schedule.")
    if re.search(r"construction_loan|construction loan|construction_interest|lease.up|lease_up", text):
        cashflow.append("Construction and lease-up need dated draws, operating start and debt conversion terms.")
    contexts = metrics.get("_fact_context") or {}
    classes = {c.get("investor_class") for c in contexts.values() if isinstance(c, dict) and c.get("investor_class") not in {None, "", "unspecified"}}
    class_labels = set(re.findall(r"\bclass[ _-]+([a-z0-9]+)\b", text))
    if len(classes) > 1 or len(class_labels) > 1 or re.search(r"investor_classes|share_classes|class_waterfall|preferred_equity", text):
        waterfall.append("Multiple equity classes require explicit class capital, priority and distribution schedules.")
    if re.search(r"catch[ _-]?up|\birr\s+hurdle|\bhurdle\s+irr|compound|tax.allocation", text):
        waterfall.append("Catch-up, IRR hurdles, compounding or tax allocation terms exceed the simple waterfall model.")
    return {"cashflow": cashflow, "waterfall": waterfall}


def limitations_for(metrics, model):
    # The analysis snapshot carries constraints from all source fields, including
    # fields deliberately excluded from accepted numeric inputs.
    retained = (metrics.get("_model_limits") or {}).get(model, [])
    return list(dict.fromkeys([*retained, *model_limits(metrics)[model]]))
