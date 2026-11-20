"""Verify bounded extraction and source identity used by the live intake replay."""

import pytest


def test_locator_keeps_pdf_page_source_and_selected_debt_case():
    from scripts.source_replay import Locator, SourceReplayBlocked, fact_from_locator

    quote = "Debt Coverage\n1.10x\t1.35x"
    locator = Locator(path="underwriting_checks.dscr", page=2, anchor="Debt Coverage",
                      kind="multiple", index=1, context={"debt_phase": "permanent"})
    fact = fact_from_locator({1: "Debt Coverage 2x 3x", 2: quote}, 9, locator)
    assert (fact.value, fact.source_doc_id, fact.source_page) == (1.35, 9, 2)
    assert fact.source_excerpt == "Debt Coverage 1.10x 1.35x"
    assert fact.debt_phase == "permanent"
    with pytest.raises(SourceReplayBlocked):
        fact_from_locator({1: quote, 2: "Debt coverage 1.10x"}, 9, locator)


def test_cashflow_selection_uses_verbatim_order_and_keeps_the_neighboring_example_out():
    from scripts.source_replay import CashFlowSelection, crosscheck_from_selection, SourceReplayBlocked

    page = ("Annual Investor Distributions\nCash Flow 2030 2031* 2032^\n"
            "LP Investor Cash Flow $(100,000) $- $121,000\nExample Subscription $40,000\n"
            "* Re-finance in November 2031\n^ Sale in December 2032")
    selection = CashFlowSelection.model_validate({
        "page": 4, "section": "Annual Investor Distributions", "header": "Cash Flow", "row": "LP Investor Cash Flow",
        "investor_class": "LP Investor", "scenario": "sale", "currency": "$",
        "events": [
            {"flow_scope": "refinance", "quote": {"page": 4, "anchor": "Re-finance in", "through": "month"}},
            {"flow_scope": "sale", "quote": {"page": 4, "anchor": "Sale in", "through": "month"}},
        ],
    })
    result = crosscheck_from_selection({4: page}, 18, selection)
    assert [row.amount for row in result.rows] == [-100000, 0, 121000]
    assert [row.flow_scope for row in result.rows] == ["unspecified", "refinance", "sale"]
    assert result.rows[-1].event_citation.source_excerpt == "Sale in December 2032"
    assert "Example Subscription" not in result.table.citation.source_excerpt
    with pytest.raises(SourceReplayBlocked):
        crosscheck_from_selection({4: page.replace("$-", "Missing")}, 18, selection)
