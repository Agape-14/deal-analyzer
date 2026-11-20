"""Describe the source-supported criteria behind each published score."""

import math


SCORE_CATEGORIES = ("returns", "market", "structure", "risk", "financials", "underwriting", "sponsor")


def _numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def comparison_basis(scores, facts):
    from app.services.analysis import digest

    policy = (scores.get("input_policy"), scores.get("score_policy"))
    output = {}
    for category in SCORE_CATEGORIES:
        score = scores.get(category) or {}
        if not _numeric(score.get("score")):
            continue
        inputs = sorted(set(path for path in score.get("supported_inputs") or [] if isinstance(path, str)))
        scoped = []
        unknown = not inputs or not all(policy)
        for path in inputs:
            fact = facts.get(path) or {}
            identity = fact.get("identity") or {}
            dimensions = ("unit", "scenario", "investor_class", "basis", "period", "debt_phase", "currency")
            scope = {key: str(identity.get(key) or "unspecified").strip().casefold() for key in dimensions}
            if not identity or (path.startswith("target_returns.") and path not in {"target_returns.total_fee_drag"}
                and any(scope[key] in {"", "unspecified", "unknown"}
                        for key in ("scenario", "investor_class", "basis", "period"))):
                unknown = True
            scoped.append((path, scope))
        output[category] = {
            "signature": None if unknown else digest((policy, score.get("weight"), scoped)),
            "inputs": [facts.get(path, {}).get("label") or path.rsplit(".", 1)[-1].replace("_", " ") for path in inputs],
        }
    if _numeric(scores.get("overall")):
        signatures = [output.get(category, {}).get("signature") for category in SCORE_CATEGORIES]
        output["overall"] = {
            "signature": digest(signatures) if all(signatures) else None,
            "inputs": [category.title() for category in SCORE_CATEGORIES if category in output],
        }
    return output
