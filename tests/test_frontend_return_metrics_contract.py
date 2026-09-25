from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_deal_ui_uses_shared_headline_return_helper():
    """Prevent cash-on-cash from being reintroduced as a hard-coded Target IRR."""
    component_files = [
        ROOT / "web" / "src" / "components" / "deal-detail" / "hero.tsx",
        ROOT / "web" / "src" / "components" / "deal-detail" / "overview-tab.tsx",
        ROOT / "web" / "src" / "components" / "deal-card.tsx",
    ]

    for path in component_files:
        source = path.read_text(encoding="utf-8")

        assert "getHeadlineReturnMetrics" in source

# Return selection behavior is exercised by web/tests/return-metrics.test.cjs.
# Avoid whitespace-dependent assertions against TypeScript source text.
