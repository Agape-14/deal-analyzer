"""Synthetic PDF witnesses for independent investor cash-flow arithmetic."""
import copy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.services.return_crosscheck import (
    CROSSCHECK_KEY, _money, checked_return_crosscheck,
    project_return_crosscheck, return_crosscheck_output_schema,
)

SCOPE = "Net LP annual cash flows for the sale scenario, in USD."
SHA_A = "a" * 64


def pdf_sources(pages, *, filename="cash-flows.pdf", document_id=1, file_hash=SHA_A):
    document = SimpleNamespace(id=document_id, filename=filename, source_role="active",
        file_sha256=file_hash, file_path="", page_count=len(pages),
        extracted_text="\n".join(f"--- Page {number} ---\n{body}" for number, body in enumerate(pages, 1)),
        extraction_quality={"status": "extracted"})
    manifest = {"id": document_id, "filename": filename, "page_count": len(pages),
                "file_sha256": file_hash, "content_hash": file_hash,
                "source_role": "active", "included_in_review": True}
    return [document], [manifest]


def citation(quote, page=1, document_id=1):
    return {"source_doc_id": document_id, "source_page": page, "source_excerpt": quote}


def vertical_case(amounts=(-100000, 10000, 110000)):
    quotes = []
    for year, amount in enumerate(amounts):
        money = "($" + format(abs(amount), ",.0f") + ")" if amount < 0 else "$" + format(amount, ",.0f")
        quotes.append(f"Year {year} LP cash flow: {money}.")
    documents, manifest = pdf_sources([SCOPE + "\n" + "\n".join(quotes)])
    payload = {"investor_class": "LP", "scenario": "sale", "basis": "net", "currency": "USD",
               "scope_citation": citation(SCOPE),
               "rows": [{"year": year, "amount": amount, "citation": citation(quote)}
                        for year, (amount, quote) in enumerate(zip(amounts, quotes))]}
    return payload, documents, manifest


def horizontal_case():
    scope = "Net LP annual cash flows for the sale scenario, amounts in $."
    header = "Year 0[1] | Year 1(2) | Year 2*"
    cash_row = "LP cash flow ($100,000) $- $121,000"
    quote = "\n".join([scope, header, cash_row])
    documents, manifest = pdf_sources([quote])
    payload = {"investor_class": "LP", "scenario": "sale", "basis": "net", "currency": "$",
               "table": {"citation": citation(quote), "year_header": header, "cash_flow_row": cash_row},
               "rows": [{"year": year, "amount": amount}
                        for year, amount in enumerate((-100000, 0, 121000))]}
    return payload, documents, manifest


def test_source_checked_series_calculates_annual_irr_and_cash_flow_multiple():
    payload, documents, manifest = vertical_case()
    record = checked_return_crosscheck(payload, documents, manifest)
    result = record["result"]
    assert result["status"] == "current"
    assert result["annual_irr_pct"] == 10
    assert result["cash_flow_multiple"] == 1.2
    assert result["investor_class"] == "LP" and result["basis"] == "net"
    assert result["rows"][0]["amount"] == -100000
    assert result["rows"][0]["label"] == "Year 0"
    assert result["rows"][1]["flow_scope"] == "unspecified"
    assert all(row["date_label"] is None for row in result["rows"])
    assert result["rows"][0]["evidence"][0]["page"] == 1
    assert result["evidence"][0]["content_hash"] == SHA_A
    assert "total positive" in result["calculation_basis"]
    assert "target_returns" not in record


def test_single_table_quote_supports_ordered_columns_explicit_zero_and_year_footnotes():
    payload, documents, manifest = horizontal_case()
    result = checked_return_crosscheck(payload, documents, manifest)["result"]
    assert result["annual_irr_pct"] == 10
    assert result["cash_flow_multiple"] == 1.21
    assert [row["amount"] for row in result["rows"]] == [-100000, 0, 121000]
    assert len(result["evidence"]) == 1
    assert all(row["evidence"][0]["excerpt"] == payload["table"]["citation"]["source_excerpt"] for row in result["rows"])


@pytest.mark.parametrize("quote,expected", [
    ("LP cash flow ($100,000) $- $121,000", [-100000, 0, 121000]),
    ("LP cash flow ($100,000) $- $- $121,000", [-100000, 0, 0, 121000]),
    ("LP cash flow $- $-100,000 $20,000", [0, -100000, 20000]),
    ("LP cash flow ($100,000) $- -$12,000 $121,000", [-100000, 0, -12000, 121000]),
    ("LP cash flow ($100,000) $- ($12,000) $121,000", [-100000, 0, -12000, 121000]),
    ("LP cash flow ($100,000) $– $121,000", [-100000, 0, 121000]),
    ("LP cash flow ($100,000)\n$-\n$121,000", [-100000, 0, 121000]),
    ("LP cash flow ($100,000) $-\t$121,000", [-100000, 0, 121000]),
])
def test_quoted_money_keeps_zero_columns_and_following_signed_amounts_in_source_order(quote, expected):
    assert [amount for amount, _ in _money(quote)] == expected


def test_calendar_table_preserves_hyphenated_refinance_and_sale_footnotes():
    scope = "Estimated annual LP Investor cash flows"
    header = "Cash Flow 2030 2031** 2032^"
    cash_row = "LP Investor Cash Flow $(200,000) $40,000 $240,000"
    table = "\n".join((scope, header, cash_row))
    refi = "** Re-finance in September 2031"
    sale = "^ Sale in May 2032"
    documents, manifest = pdf_sources(["\n".join((table, refi, sale))])
    record = checked_return_crosscheck({
        "investor_class": "LP Investor", "scenario": "sale", "currency": "$",
        "table": {"citation": citation(table), "year_header": header, "cash_flow_row": cash_row},
        "rows": [
            {"year": 2030, "amount": -200000},
            {"year": 2031, "amount": 40000, "flow_scope": "refinance", "event_citation": citation(refi)},
            {"year": 2032, "amount": 240000, "flow_scope": "sale", "event_citation": citation(sale)},
        ],
    }, documents, manifest)
    result = record["result"]
    assert result["annual_irr_pct"] == 20 and result["cash_flow_multiple"] == 1.4
    assert [row["label"] for row in result["rows"]] == ["2030", "2031", "2032"]
    assert result["rows"][1]["flow_scope_label"] == "Includes refinance proceeds"


def test_class_a_refinance_and_sale_years_keep_total_cash_flows_at_twenty_percent_irr():
    payload, documents, manifest = vertical_case((-100000, 20000, 120000))
    payload["investor_class"] = "Class A"
    payload["scope_citation"]["source_excerpt"] = SCOPE.replace("LP", "Class A")
    documents[0].extracted_text = documents[0].extracted_text.replace("LP", "Class A")
    for row in payload["rows"]:
        row["citation"]["source_excerpt"] = row["citation"]["source_excerpt"].replace("LP", "Class A")
    for year, flow_scope, event in [
        (1, "refinance", "Year 1 cash flow includes refinance proceeds."),
        (2, "sale", "Year 2 cash flow includes sale proceeds."),
    ]:
        documents[0].extracted_text += "\n" + event
        payload["rows"][year].update(flow_scope=flow_scope, event_citation=citation(event))
    result = checked_return_crosscheck(payload, documents, manifest)["result"]
    assert result["annual_irr_pct"] == 20
    assert result["cash_flow_multiple"] == 1.4
    assert result["rows"][1]["amount"] == 20000
    assert result["rows"][1]["flow_scope_label"] == "Includes refinance proceeds"
    assert result["rows"][2]["amount"] == 120000
    assert result["rows"][2]["flow_scope_label"] == "Includes sale proceeds"


@pytest.mark.parametrize("change", [
    {"amount": 100000}, {"amount": -99999}, {"year": 3},
])
def test_signed_amount_and_annual_period_cannot_be_changed(change):
    payload, documents, manifest = vertical_case()
    payload["rows"][0].update(change)
    with pytest.raises((ValueError, ValidationError)):
        checked_return_crosscheck(payload, documents, manifest)


@pytest.mark.parametrize("years", [[0, 2, 3], [0, 0, 1], [2, 1, 0]])
def test_missing_duplicate_or_reversed_annual_periods_are_rejected(years):
    payload, documents, manifest = vertical_case()
    for row, year in zip(payload["rows"], years):
        row["year"] = year
    with pytest.raises(ValidationError):
        checked_return_crosscheck(payload, documents, manifest)


def test_wrong_pdf_page_and_workbook_sources_are_rejected():
    payload, documents, manifest = vertical_case()
    payload["rows"][1]["citation"]["source_page"] = 2
    with pytest.raises(ValueError):
        checked_return_crosscheck(payload, documents, manifest)
    payload, documents, manifest = vertical_case()
    documents[0].filename = manifest[0]["filename"] = "cash-flows.xlsx"
    with pytest.raises(ValueError, match="PDF"):
        checked_return_crosscheck(payload, documents, manifest)


def test_table_cannot_swap_cash_flows_or_relabel_year_columns():
    payload, documents, manifest = horizontal_case()
    payload["rows"][1]["amount"], payload["rows"][2]["amount"] = 121000, 0
    with pytest.raises(ValueError, match="signed cash-flow amounts"):
        checked_return_crosscheck(payload, documents, manifest)
    payload, documents, manifest = horizontal_case()
    payload["table"]["year_header"] = "Year 1 | Year 2 | Year 3"
    with pytest.raises(ValueError):
        checked_return_crosscheck(payload, documents, manifest)


def test_a_gp_row_cannot_be_published_as_lp_cash_flow():
    payload, documents, manifest = horizontal_case()
    payload["table"]["cash_flow_row"] = payload["table"]["cash_flow_row"].replace("LP cash flow", "GP cash flow")
    payload["table"]["citation"]["source_excerpt"] = payload["table"]["citation"]["source_excerpt"].replace("LP cash flow (", "GP cash flow (")
    documents[0].extracted_text = "--- Page 1 ---\n" + payload["table"]["citation"]["source_excerpt"]
    with pytest.raises(ValueError, match="another investor"):
        checked_return_crosscheck(payload, documents, manifest)


@pytest.mark.parametrize("event", [
    "Year 1 LP cash flow includes sale proceeds.",
    "LP cash flow includes sale proceeds.",
    "Year 2 LP cash flow excludes sale proceeds.",
    "Year 2 GP cash flow includes sale proceeds.",
])
def test_event_annotations_require_the_correct_year_and_investor_context(event):
    payload, documents, manifest = vertical_case()
    documents[0].extracted_text += "\n" + event
    payload["rows"][2].update(flow_scope="sale", event_citation=citation(event))
    with pytest.raises(ValueError):
        checked_return_crosscheck(payload, documents, manifest)


def test_a_cited_footnote_can_identify_mixed_sale_cash_flow_without_splitting_it():
    payload, documents, manifest = vertical_case()
    event = "Year 2 LP total cash flow includes operating distributions and sale proceeds."
    documents[0].extracted_text += "\n--- Page 2 ---\n" + event
    documents[0].page_count = manifest[0]["page_count"] = 2
    payload["rows"][2].update(flow_scope="sale", event_citation=citation(event, page=2))
    row = checked_return_crosscheck(payload, documents, manifest)["result"]["rows"][2]
    assert row["amount"] == 110000
    assert row["flow_scope_label"] == "Includes sale proceeds"
    assert row["event_evidence"][0]["page"] == 2
    assert "operating_amount" not in row and "sale_amount" not in row


def test_refinancing_annotation_can_apply_to_an_explicit_source_year_range():
    payload, documents, manifest = vertical_case()
    event = "Years 1–2 LP cash flows include refinancing proceeds."
    documents[0].extracted_text += "\n" + event
    for row in payload["rows"][1:]:
        row.update(flow_scope="refinance", event_citation=citation(event))
    rows = checked_return_crosscheck(payload, documents, manifest)["result"]["rows"]
    assert [row["flow_scope_label"] for row in rows[1:]] == ["Includes refinance proceeds"] * 2


def test_known_date_labels_are_preserved_verbatim_and_unknown_dates_stay_empty():
    payload, documents, manifest = vertical_case()
    quote = "Year 0, contribution dated June 2028: LP cash flow ($100,000)."
    documents[0].extracted_text += "\n" + quote
    payload["rows"][0].update(citation=citation(quote), date_label="June 2028")
    rows = checked_return_crosscheck(payload, documents, manifest)["result"]["rows"]
    assert rows[0]["date_label"] == "June 2028"
    assert rows[1]["date_label"] is None
    payload["rows"][0]["date_label"] = "2028-06-01"
    with pytest.raises(ValueError, match="date label"):
        checked_return_crosscheck(payload, documents, manifest)


def test_dates_in_a_horizontal_header_must_belong_to_their_own_year_column():
    payload, documents, manifest = horizontal_case()
    header = "Year 0 June 2028 | Year 1 June 2029 | Year 2 June 2030"
    old_header = payload["table"]["year_header"]
    payload["table"]["year_header"] = header
    payload["table"]["citation"]["source_excerpt"] = payload["table"]["citation"]["source_excerpt"].replace(old_header, header)
    documents[0].extracted_text = "--- Page 1 ---\n" + payload["table"]["citation"]["source_excerpt"]
    payload["rows"][0]["date_label"] = "June 2028"
    assert checked_return_crosscheck(payload, documents, manifest)["result"]["rows"][0]["date_label"] == "June 2028"
    payload["rows"][0]["date_label"] = "June 2029"
    with pytest.raises(ValueError, match="table column"):
        checked_return_crosscheck(payload, documents, manifest)


def test_multiple_irr_roots_are_withheld_while_the_inflow_outflow_multiple_is_defined():
    payload, documents, manifest = vertical_case((-100000, 230000, -132000))
    result = checked_return_crosscheck(payload, documents, manifest)["result"]
    assert result["annual_irr_pct"] is None
    assert result["cash_flow_multiple"] == pytest.approx(230000 / 232000, abs=1e-6)
    assert "one negative-to-positive" in result["warnings"][0]


def test_consecutive_initial_contributions_with_one_sign_change_are_supported():
    payload, documents, manifest = vertical_case((-100000, -10000, 132000))
    result = checked_return_crosscheck(payload, documents, manifest)["result"]
    assert result["annual_irr_pct"] == 10
    assert result["cash_flow_multiple"] == 1.2


def test_unrelated_uploads_and_same_bytes_with_a_new_text_hash_do_not_stale_the_check():
    payload, documents, manifest = vertical_case()
    record = checked_return_crosscheck(payload, documents, manifest)
    current = copy.deepcopy(manifest)
    current[0]["content_hash"] = "new-reader-representation"
    current.append({**manifest[0], "id": 2, "filename": "other-source.pdf", "file_sha256": "b" * 64, "content_hash": "b" * 64})
    projected = project_return_crosscheck({CROSSCHECK_KEY: record}, current)
    assert projected["status"] == "current" and projected["annual_irr_pct"] == 10


@pytest.mark.parametrize("change", [
    {"file_sha256": "b" * 64}, {"included_in_review": False},
])
def test_changed_or_inactive_cited_pdf_preserves_old_evidence_and_withholds_active_results(change):
    payload, documents, manifest = vertical_case()
    record = checked_return_crosscheck(payload, documents, manifest)
    current = copy.deepcopy(manifest)
    current[0].update(change)
    projected = project_return_crosscheck({CROSSCHECK_KEY: record}, current)
    assert projected["status"] == "needs_review"
    assert projected["annual_irr_pct"] is None and projected["cash_flow_multiple"] is None
    assert projected["previous_calculation"] == {"annual_irr_pct": 10, "cash_flow_multiple": 1.2}
    assert projected["evidence"][0]["content_hash"] == SHA_A
    assert record["result"]["status"] == "current"


def test_known_same_filename_versions_are_current_until_a_new_version_appears():
    payload, documents, manifest = vertical_case()
    known = {**manifest[0], "id": 2, "file_sha256": "b" * 64, "content_hash": "b" * 64}
    manifest.append(known)
    record = checked_return_crosscheck(payload, documents, manifest)
    assert project_return_crosscheck({CROSSCHECK_KEY: record}, manifest)["status"] == "current"
    newer = [*manifest, {**known, "id": 3, "file_sha256": "c" * 64, "content_hash": "c" * 64}]
    projected = project_return_crosscheck({CROSSCHECK_KEY: record}, newer)
    assert projected["status"] == "needs_review"
    assert "active_filename_version_added" in projected["stale_reasons"]


def test_changed_input_or_missing_binding_cannot_be_presented_as_a_verified_calculation():
    payload, documents, manifest = vertical_case()
    record = checked_return_crosscheck(payload, documents, manifest)
    changed = copy.deepcopy(record)
    changed["input"]["rows"][1]["amount"] = 999999
    assert project_return_crosscheck({CROSSCHECK_KEY: changed}, manifest) is None
    changed = copy.deepcopy(record)
    changed["bindings"] = []
    assert project_return_crosscheck({CROSSCHECK_KEY: changed}, manifest) is None
    changed = copy.deepcopy(record)
    changed["result"]["annual_irr_pct"] = 99
    assert project_return_crosscheck({CROSSCHECK_KEY: changed}, manifest)["annual_irr_pct"] == 10


def test_currency_labels_and_amount_limits_do_not_invent_an_iso_unit():
    payload, documents, manifest = horizontal_case()
    payload["currency"] = "USD"
    with pytest.raises(ValueError, match="currency label"):
        checked_return_crosscheck(payload, documents, manifest)
    payload["currency"] = "usd"
    with pytest.raises(ValidationError):
        checked_return_crosscheck(payload, documents, manifest)
    payload, documents, manifest = vertical_case()
    payload["rows"][0]["amount"] = -1e16
    with pytest.raises(ValidationError):
        checked_return_crosscheck(payload, documents, manifest)


def test_provider_schema_requires_all_nested_properties_and_contains_no_defaults():
    schema = return_crosscheck_output_schema()
    def visit(value):
        if isinstance(value, dict):
            assert "default" not in value
            if "properties" in value:
                assert set(value["required"]) == set(value["properties"])
                assert value["additionalProperties"] is False
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(schema)
    assert "$defs" in schema
