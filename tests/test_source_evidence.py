"""Source checks must be reproducible, current, and independent of old labels."""
from types import SimpleNamespace

import pytest

from app.services.data_integrity import mark_manual_edit, stamp_verification
from app.services.deal_verifier import apply_corrections
from app.services.document_context import select_context_for_sections
from app.services.spreadsheet_extractor import extract_spreadsheet


def document(name="Current.pdf", text="--- Page 1 ---\nInvestor return is 12.5%."):
    return SimpleNamespace(id=2, filename=name, extracted_text=text, page_count=1,
                           file_sha256="current-hash", file_path="", extraction_quality={},
                           source_role="active", superseded_by_id=None)


def audit(**kwargs):
    return {"section": "target_returns", "field": "target_irr", "status": "confirmed",
            "extracted_value": 12.5, "source_doc_name": "Current.pdf", "source_page": 1,
            "source": "Current.pdf Page 1", "source_excerpt": "Investor return is 12.5%.", **kwargs}


def stamp(row, metrics=None, docs=None):
    metrics = metrics or {"target_returns": {"target_irr": 12.5}}
    return stamp_verification(metrics, {"audit_results": [row]}, docs or [document()])


def test_new_citation_replaces_stale_id_page_context_and_note():
    path = "target_returns.target_irr"
    metrics = {"target_returns": {"target_irr": 12.5}, "_fact_context": {path: {"investor_class": "Old"}},
               "_provenance": {path: {"source_doc_id": 999, "source_page": 99, "source_sheet": "Old",
                                     "source_cell": "C99", "verification_note": "old dispute"}}}
    result = stamp(audit(), metrics)
    evidence = result["_provenance"][path]
    assert evidence["status"] == "confirmed"
    assert evidence["source_doc_id"] == 2 and evidence["source_page"] == 1
    assert "source_cell" not in evidence and "source_sheet" not in evidence
    assert evidence["verification_note"] == ""
    assert path not in result["_fact_context"]


@pytest.mark.parametrize("change", [
    {"source_excerpt": "Investor return is 13.5%."},
    {"source_page": 2}, {"source_doc_id": 999}, {"source_doc_name": "Other.pdf"},
    {"source_excerpt": ""}, {"extracted_value": 11},
])
def test_unreproducible_confirmation_is_withheld_and_summary_agrees(change):
    result = stamp(audit(**change))
    assert result["_provenance"]["target_returns.target_irr"]["status"] == "unverifiable"
    assert result["_verification"]["totals"]["confirmed"] == 0
    assert result["_verification"]["totals"]["unverifiable"] == 1


def test_real_quote_with_wrong_number_cannot_confirm_current_value():
    result = stamp(audit(source_excerpt="Other return is 8.5%."), docs=[document(text="--- Page 1 ---\nOther return is 8.5%.")])
    assert result["_provenance"]["target_returns.target_irr"]["status"] == "unverifiable"


def test_locked_manual_decision_survives_fresh_source_challenge():
    metrics = mark_manual_edit({}, "target_returns.target_irr", 12.5)
    result = stamp(audit(source_page=8), metrics)
    evidence = result["_provenance"]["target_returns.target_irr"]
    assert result["target_returns"]["target_irr"] == 12.5
    assert evidence["status"] == "manual" and evidence["locked"]
    assert evidence["last_source_check"]["status"] == "unverifiable"
    assert evidence["source_challenge"]


def test_workbook_quote_requires_actual_sheet_cell_and_supports_percentage_fraction():
    doc = document("Model.xlsx", "--- Sheet: Summary ---\nA13=Investor IRR | B13=0.125\n--- Sheet: Sponsor ---\nA13=IRR | B13=0.3")
    row = audit(source_doc_name="Model.xlsx", source_page=None, source_sheet="Summary", source_cell="B13",
                source="Model.xlsx Summary B13", source_excerpt="A13=Investor IRR | B13=0.125")
    assert stamp(row, docs=[doc])["_provenance"]["target_returns.target_irr"]["status"] == "confirmed"
    assert stamp({**row, "source_sheet": "Sponsor"}, docs=[doc])["_provenance"]["target_returns.target_irr"]["status"] == "unverifiable"
    row.update(source_excerpt="A13=Investor IRR", source_cell="A13", extracted_value=13)
    assert stamp(row, {"target_returns": {"target_irr": 13}}, [doc])["_provenance"]["target_returns.target_irr"]["status"] == "unverifiable"


def test_correction_removes_old_dotted_alias_even_if_nested_value_already_correct():
    metrics = {"target_returns": {"hold_scenario": {"cash_on_cash_return": 8}, "hold_scenario.cash_on_cash_return": 25}}
    row = {"section": "target_returns", "field": "hold_scenario.cash_on_cash_return", "status": "wrong", "correct_value": 8, "source": "Memo Page 2"}
    result, changes = apply_corrections(metrics, {"audit_results": [row]})
    assert changes and "hold_scenario.cash_on_cash_return" not in result["target_returns"]
    assert result["target_returns"]["hold_scenario"]["cash_on_cash_return"] == 8


def test_detailed_workbook_keeps_late_rows_wide_columns_gaps_and_uncached_formulas(tmp_path):
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.title = "Cash Flow"
    sheet["A294"] = "Investor cash flow"
    sheet["DA449"] = 9876
    sheet["C450"] = "=1+2"
    path = tmp_path / "model.xlsx"
    book.save(path)
    result = extract_spreadsheet(str(path))
    assert "A294=Investor cash flow" in result.text
    assert "DA449=9876" in result.text
    assert "C450=[formula has no cached value]" in result.text
    assert not result.page_diagnostics[0]["truncated"]


def test_focused_context_keeps_late_investor_rows_and_later_documents():
    rows = [f"A{i}=Routine row | B{i}=10000" for i in range(1, 450)]
    rows[350] = "A351=Investor cash flow return IRR multiple distributions preferred | B351=0.125"
    workbook = "--- Sheet: Cash Flow ---\n" + "\n".join(rows)
    result, _ = select_context_for_sections([
        {"filename": "large.xlsx", "text": workbook},
        {"filename": "amendment.pdf", "text": "--- Page 1 ---\nCurrent investor terms."}],
        ["target_returns"], max_chars=4000, full_text_threshold_chars=1000)
    assert "B351=0.125" in result
    assert "Current investor terms." in result
    assert len(result) <= 4000


def test_review_batches_bound_nested_field_count_without_losing_identity():
    from app.services.deal_verifier import verification_batches
    metrics = {"target_returns": {"hold_scenario": {f"field_{i}": i for i in range(29)}, "zero": 0, "missing": None}}
    batches = verification_batches(metrics, ["target_returns"], 12)
    assert [sum(len(values) for values in batch.values()) for batch in batches] == [12, 12, 7]
    combined = {field: value for batch in batches for field, value in batch["target_returns"].items()}
    assert combined["hold_scenario.field_28"] == 28
    assert combined["zero"] == 0 and combined["missing"] is None


@pytest.mark.asyncio
async def test_truncated_review_retries_smaller_batches_without_using_partial_json(monkeypatch):
    from app.services import deal_verifier as verifier
    calls = []
    async def reply(sections, subset, *args):
        calls.append(list(subset["target_returns"]))
        if len(calls[-1]) > 1:
            raise verifier.VerificationOutputLimit("truncated")
        return {"audit_results": [{"field": calls[-1][0]}]}
    monkeypatch.setattr(verifier, "_verify_sections", reply)
    result = await verifier._verify_bounded_batch({"target_returns": {"a": 1, "b": 2, "c": 3}}, [], [], "test", 1)
    assert len(result["audit_results"]) == 3
    assert calls == [["a", "b", "c"], ["a"], ["b"], ["c"]]


@pytest.mark.asyncio
async def test_single_field_output_limit_fails_without_an_infinite_retry(monkeypatch):
    from app.services import deal_verifier as verifier
    calls = []
    async def reply(*args):
        calls.append(1)
        raise verifier.VerificationOutputLimit("truncated")
    monkeypatch.setattr(verifier, "_verify_sections", reply)
    with pytest.raises(verifier.VerificationOutputLimit):
        await verifier._verify_bounded_batch({"target_returns": {"a": 1}}, [], [], "test", 1)
    assert calls == [1]


@pytest.mark.asyncio
async def test_provider_omission_cannot_keep_an_old_confirmation_or_audit_other_fields(monkeypatch):
    from app.services import deal_verifier as verifier
    async def reply(*args):
        return {"audit_results": [{"section": "target_returns", "field": "unrequested", "status": "confirmed"}]}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic")
    monkeypatch.setattr(verifier, "_verify_bounded_batch", reply)
    deal = SimpleNamespace(id=1, documents=[document()], metrics={"target_returns": {"target_irr": 12.5}})
    result = await verifier.verify_deal_metrics(deal, None)
    assert len(result["audit_results"]) == 1
    assert result["audit_results"][0]["field"] == "target_irr"
    assert result["audit_results"][0]["status"] == "unverifiable"
