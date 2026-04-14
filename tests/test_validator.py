"""Tests for the asset-class-aware deal validator."""

from app.services.deal_validator import (
    ASSET_CLASS_PROFILES,
    DEFAULT_PROFILE,
    validate_deal_metrics,
)


def _irr_flag(flags):
    return next((f for f in flags if "aggressive" in f.get("message", "")), None)


def test_multifamily_flags_32pct_irr():
    flags = validate_deal_metrics({"target_returns": {"target_irr": 32}}, "multifamily")
    assert _irr_flag(flags) is not None


def test_development_does_not_flag_32pct_irr():
    flags = validate_deal_metrics({"target_returns": {"target_irr": 32}}, "development")
    # 32% is below development's 35% cap
    assert _irr_flag(flags) is None


def test_land_allows_even_higher_irr():
    flags = validate_deal_metrics({"target_returns": {"target_irr": 38}}, "land")
    assert _irr_flag(flags) is None


def test_unknown_property_type_falls_back_to_default():
    flags = validate_deal_metrics({"target_returns": {"target_irr": 32}}, "self-storage")
    assert _irr_flag(flags) is not None  # uses default (multifamily-ish)


def test_profile_coverage():
    # Every profile carries every key in DEFAULT_PROFILE — prevents bug where
    # a new default threshold exists in some profiles but not others.
    keys = set(DEFAULT_PROFILE.keys())
    for name, prof in ASSET_CLASS_PROFILES.items():
        missing = keys - set(prof.keys())
        assert not missing, f"{name} missing keys: {missing}"


def test_ltv_threshold_varies_by_asset_class():
    # 72% LTV: red on multifamily (>75% red, >65% yellow → actually 72% = yellow
    # on multifamily too). Red on multifamily only above 75. Here we test that
    # development with its 80% red threshold doesn't red-flag 72.
    m = {"deal_structure": {"ltv": 72}}
    mf = validate_deal_metrics(m, "multifamily")
    dev = validate_deal_metrics(m, "development")
    # Multifamily: 72 > 65 yellow threshold, < 75 red → yellow flag
    assert any(
        f["severity"] == "yellow" and "LTV of 72" in f["message"] for f in mf
    )
    # Development: LTV thresholds are wider (70/80); 72 > 70 yellow, < 80 red → yellow
    assert any(
        f["severity"] == "yellow" and "LTV of 72" in f["message"] for f in dev
    )
    # Both flag yellow here, which is the point — but neither should red-flag
    assert not any(f["severity"] == "red" and "LTV" in f.get("category", "") for f in mf)
    assert not any(f["severity"] == "red" and "LTV" in f.get("category", "") for f in dev)


def test_empty_metrics_returns_empty_flags_gracefully():
    assert validate_deal_metrics({}, None) == []
    assert validate_deal_metrics({}, "multifamily") == []
