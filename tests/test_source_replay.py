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
