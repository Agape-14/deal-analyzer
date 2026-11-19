"""A native heading must not hide a budget table stored as an image."""
from types import SimpleNamespace

import fitz
import pytest

from app.services import pdf_extractor
from app.services.document_versions import document_payloads


HEADING = "Project preliminary investment overview and development cost summary"


def source_pdf(tmp_path, *, image=None, heading=HEADING):
    filename = tmp_path / "budget.pdf"
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        page.insert_text((40, 40), heading)
        if image is not None:
            pixels = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200), False)
            pixels.clear_with(255)
            page.insert_image(image, pixmap=pixels)
        document.save(filename)
    return str(filename)


def test_sparse_native_heading_gets_image_table_ocr_without_losing_native_text(tmp_path, monkeypatch):
    filename = source_pdf(tmp_path, image=fitz.Rect(40, 150, 560, 740))
    monkeypatch.setattr(pdf_extractor, "_ocr_page", lambda page: "Hard costs $500,000\nSoft costs $100,000\nTotal construction costs $600,000")

    result = pdf_extractor.extract_pdf(filename)

    assert HEADING in result.text
    assert "Total construction costs $600,000" in result.text
    assert result.ocr_page_count == 1
    assert result.page_diagnostics[0]["source"] == "ocr_image"
    assert not result.page_diagnostics[0]["image_text_unread"]
    assert result.quality_score == 100


@pytest.mark.parametrize("ocr_text,ocr_pages", [("", 0), (HEADING, 0), (HEADING + "\n$500", 1)])
def test_unread_large_image_is_flagged_despite_usable_native_heading(tmp_path, monkeypatch, ocr_text, ocr_pages):
    filename = source_pdf(tmp_path, image=fitz.Rect(40, 150, 560, 740))
    monkeypatch.setattr(pdf_extractor, "_ocr_page", lambda page: ocr_text)

    result = pdf_extractor.extract_pdf(filename)

    assert HEADING in result.text
    assert result.ocr_page_count == ocr_pages
    assert result.page_diagnostics[0]["source"] == "image_text_unread"
    assert result.page_diagnostics[0]["image_text_unread"]
    assert result.quality_score < 100
    document = SimpleNamespace(
        id=1, filename="budget.pdf", file_sha256="synthetic-file-hash", doc_type="offering_memo",
        page_count=1, upload_date=None, extracted_text=result.text,
        extraction_quality={"page_diagnostics": result.page_diagnostics, "quality_score": result.quality_score},
    )
    warnings = document_payloads([document])[0]["extraction_quality"]["warnings"]
    assert any("pages 1" in warning and "could not be fully read" in warning for warning in warnings)


def test_sparse_native_page_with_small_logo_uses_existing_text(tmp_path, monkeypatch):
    filename = source_pdf(tmp_path, image=fitz.Rect(40, 150, 80, 190))

    def unexpected_ocr(page):
        raise AssertionError("A small logo should not trigger page OCR.")

    monkeypatch.setattr(pdf_extractor, "_ocr_page", unexpected_ocr)
    result = pdf_extractor.extract_pdf(filename)

    assert result.ocr_page_count == 0
    assert result.page_diagnostics[0]["source"] == "text"
    assert result.quality_score == 100


def test_ocr_containing_native_heading_does_not_duplicate_it(tmp_path, monkeypatch):
    filename = source_pdf(tmp_path, image=fitz.Rect(40, 150, 560, 740))
    monkeypatch.setattr(pdf_extractor, "_ocr_page", lambda page: HEADING + "\nLand acquisition $120,000\nProject costs $720,000")

    result = pdf_extractor.extract_pdf(filename)

    assert result.text.count(HEADING) == 1
    assert "Project costs $720,000" in result.text
    assert result.page_diagnostics[0]["source"] == "ocr_image"


def test_existing_near_empty_page_ocr_keeps_text_that_ocr_misses(tmp_path, monkeypatch):
    filename = source_pdf(tmp_path, heading="Plan title")
    monkeypatch.setattr(pdf_extractor, "_ocr_page", lambda page: "Budget hard costs $500,000 and soft costs $100,000")

    result = pdf_extractor.extract_pdf(filename)

    assert "Plan title" in result.text and "hard costs $500,000" in result.text
    assert result.page_diagnostics[0]["source"] == "ocr"


def test_image_detection_tolerates_unavailable_or_invalid_image_metadata():
    def unavailable():
        raise RuntimeError("Image metadata unavailable")

    page = SimpleNamespace(rect=fitz.Rect(0, 0, 600, 800), get_image_info=unavailable)
    assert not pdf_extractor._has_large_image(page)
    page.get_image_info = lambda: [{"bbox": None}, {"bbox": (0, 0, 550, 750)}]
    assert pdf_extractor._has_large_image(page)


def table_page(rows, column_labels, *, positioned=None):
    boxes = [[(column * 100, row * 30, (column + 1) * 100, (row + 1) * 30)
              for column in range(len(values))] for row, values in enumerate(rows)]
    words = []
    for row_index, values in enumerate(rows):
        for column, value in enumerate(values):
            text = (positioned or {}).get((row_index + 1, column + 1), value)
            if text:
                x0, y0, x1, y1 = boxes[row_index][column]
                words.append((x0 + 5, y0 + 5, x1 - 5, y1 - 5, text, 0, row_index, column))
    table = SimpleNamespace(
        extract=lambda: rows, bbox=(0, 0, 100 * len(column_labels), 30 * len(rows)),
        header=SimpleNamespace(names=column_labels, external=False),
        rows=[SimpleNamespace(cells=row) for row in boxes],
    )
    return SimpleNamespace(
        find_tables=lambda: SimpleNamespace(tables=[table]),
        get_text=lambda mode=None: words if mode == "words" else "Full native source text with construction costs and financial metrics.",
        rect=fitz.Rect(0, 0, 600, 800), get_image_info=lambda: [],
    )


def native_grid_pdf(tmp_path):
    filename = tmp_path / "native-grid.pdf"
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        for x in (40, 250, 410, 560):
            page.draw_line((x, 100), (x, 205))
        for y in (100, 135, 170, 205):
            page.draw_line((40, y), (560, y))
        for y, values in ((122, ("Cost category", "Total", "Per unit")),
                          (157, ("Land", "$1,200,000", "$12,000")),
                          (192, ("Hard costs", "$5,000,000", "$50,000"))):
            for x, value in zip((50, 260, 420), values):
                page.insert_text((x, y), value)
        document.save(filename)
    return filename


def test_native_grid_keeps_headers_cells_and_citable_rows_in_page_text(tmp_path):
    filename = native_grid_pdf(tmp_path)
    result = pdf_extractor.extract_pdf(str(filename))

    table = next(table for table in result.tables if table["rows"][0][0] == "Cost category")
    assert table["page"] == 1 and table["table_index"] == 1
    assert table["column_labels"] == ["Cost category", "Total", "Per unit"]
    assert table["rows"][1] == ["Land", "$1,200,000", "$12,000"]
    row = next(row for row in table["review_rows"] if row["row"] == 2)
    assert row["text"] == "Table 1 row 2 | Cost category=Land | Total=$1,200,000 | Per unit=$12,000"
    assert row["text"] in result.text
    assert "Hard costs" in result.text
    assert result.numeric_diagnostics == []


def test_corroborated_decimal_discrepancy_is_bound_to_one_original_cell(monkeypatch):
    page = table_page([["Metric", "Rate", "Other"], ["Vacancy", "500%", "27%"]], ["Metric", "Rate", "Other"])
    monkeypatch.setattr(pdf_extractor, "_ocr_region", lambda page, box: "5.00%")

    table = pdf_extractor._extract_tables(page, 4)[0]

    assert table["rows"][1][1] == "500%"
    assert len(table["numeric_diagnostics"]) == 1
    diagnostic = table["numeric_diagnostics"][0]
    assert (diagnostic["page"], diagnostic["table_index"], diagnostic["row"], diagnostic["column"]) == (4, 1, 2, 2)
    assert diagnostic["code"] == "possible_dropped_decimal"
    assert diagnostic["native_token"] == "500%" and diagnostic["corroborating_token"] == "5.00%"
    assert diagnostic["corroborating_source"] == "rendered_cell_ocr"
    assert diagnostic["source_row"] == table["review_rows"][1]["text"]
    assert "correct_value" not in diagnostic and "repaired_value" not in diagnostic


def test_native_and_rendered_numbers_remain_distinct_when_they_disagree(monkeypatch):
    page = table_page([["Metric", "Total"], ["Loan principal", "$36,000,000"]],
                      ["Metric", "Total"], positioned={(2, 2): "$35,000,000"})
    monkeypatch.setattr(pdf_extractor, "_ocr_region", lambda page, box: "$35,000,000")

    table = pdf_extractor._extract_tables(page, 2)[0]

    diagnostic = table["numeric_diagnostics"][0]
    assert diagnostic["code"] == "numeric_text_disagreement"
    assert diagnostic["native_token"] == "$36,000,000"
    assert diagnostic["corroborating_token"] == "$35,000,000"
    assert table["rows"][1][1] == "$36,000,000"


def test_coverage_ratio_decimal_requires_corroboration_and_keeps_original(monkeypatch):
    page = table_page([["Metric", "Ratio"], ["DSCR", "125"]], ["Metric", "Ratio"])
    monkeypatch.setattr(pdf_extractor, "_ocr_region", lambda page, box: "1.25")
    table = pdf_extractor._extract_tables(page, 3)[0]
    diagnostic = table["numeric_diagnostics"][0]
    assert diagnostic["code"] == "possible_dropped_decimal"
    assert diagnostic["native_token"] == "125" and diagnostic["corroborating_token"] == "1.25"
    assert table["rows"][1][1] == "125"


def test_large_return_percentage_does_not_trigger_proportion_heuristic(monkeypatch):
    page = table_page([["Metric", "Rate"], ["Project IRR", "250%"]], ["Metric", "Rate"])

    def unexpected_ocr(*args):
        raise AssertionError("A large IRR alone is not evidence of a dropped decimal.")

    monkeypatch.setattr(pdf_extractor, "_ocr_region", unexpected_ocr)
    assert pdf_extractor._extract_tables(page, 1)[0]["numeric_diagnostics"] == []


def test_ocr_grouping_warning_retains_exact_line_without_assuming_a_column():
    text = "Soft costs (1,234.567) per unit (9.876)\nVersion 2024.10.07\nProject IRR 250%"
    diagnostics = pdf_extractor._ocr_numeric_diagnostics(text, text, 6, pdf_extractor._read_budget())
    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert diagnostic["code"] == "ambiguous_numeric_grouping"
    assert diagnostic["source_row"] == text.splitlines()[0]
    assert diagnostic["table_index"] is None and diagnostic["column"] is None
    assert diagnostic["reading_source"] == "rendered_page_ocr"
    assert diagnostic["corroborating_token"] is None


def test_table_limits_are_document_wide_and_never_cut_a_number(monkeypatch):
    monkeypatch.setattr(pdf_extractor, "MAX_PDF_TABLES", 1)
    monkeypatch.setattr(pdf_extractor, "MAX_PDF_TABLE_CELLS", 4)
    monkeypatch.setattr(pdf_extractor, "MAX_CELL_CHARS", 12)
    monkeypatch.setattr(pdf_extractor, "MAX_PDF_REVIEW_CHARS", 180)
    page = table_page([["Metric", "Total"], ["Land", "$123,456,789,000"], ["Other", "$5"]], ["Metric", "Total"])
    budget = pdf_extractor._read_budget()

    tables = pdf_extractor._extract_tables(page, 1, budget)
    second_page = pdf_extractor._extract_tables(page, 2, budget)

    assert len(tables) == 1 and second_page == []
    assert sum(len(row) for table in tables for row in table["rows"]) <= 4
    assert budget["review_chars"] <= 180
    assert tables[0]["rows"][1][1] == "[cell text omitted]"
    assert tables[0]["truncated"]
    assert budget["truncated_pages"] == {1, 2}


def test_numeric_ocr_checks_are_bounded_across_tables_on_one_page(monkeypatch):
    first = table_page([["Metric", "Rate"], ["Vacancy", "500%"]], ["Metric", "Rate"])
    table = first.find_tables().tables[0]
    first.find_tables = lambda: SimpleNamespace(tables=[table, table])
    calls = []
    monkeypatch.setattr(pdf_extractor, "MAX_NUMERIC_CHECKS_PER_PAGE", 1)
    monkeypatch.setattr(pdf_extractor, "_ocr_region", lambda *args: calls.append(1) or "5.00%")
    budget = pdf_extractor._read_budget()

    tables = pdf_extractor._extract_tables(first, 1, budget)

    assert len(calls) == 1 and len(tables) == 2
    assert 1 in budget["unchecked_pages"]


@pytest.mark.asyncio
async def test_pdf_upload_persists_bounded_table_details_and_reviewable_rows(client, tmp_path):
    from app.database import async_session
    from app.models import DealDocument

    filename = native_grid_pdf(tmp_path)
    created = await client.post("/api/deals", json={"project_name": "Synthetic native budget table"})
    deal_id = created.json()["id"]
    uploaded = await client.post(f"/api/deals/{deal_id}/documents/upload", files={
        "file": ("budget.pdf", filename.read_bytes(), "application/pdf"),
    })
    assert uploaded.status_code == 200, uploaded.text
    async with async_session() as db:
        doc = await db.get(DealDocument, uploaded.json()["id"])
        quality = doc.extraction_quality
        assert quality["pdf_text_format_version"] == 2
        table = quality["pdf_tables"][0]
        assert table["rows"][1] == ["Land", "$1,200,000", "$12,000"]
        assert table["review_rows"][1]["text"] in doc.extracted_text
        assert quality["numeric_diagnostics"] == []
