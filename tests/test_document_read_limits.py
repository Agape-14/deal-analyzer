"""Exercise reading limits with ordinary fixtures and small test budgets."""

import zipfile

import fitz
import openpyxl
import pytest

from app.services import document_read_limits, pdf_extractor, spreadsheet_extractor


def _pdf(path, pages=1, scanned=False):
    with fitz.open() as document:
        for page_index in range(pages):
            page = document.new_page()
            page.insert_text((40, 40), f"Project terms page {page_index + 1}: total construction costs $100,000.")
            if scanned:
                pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 240), False)
                pixmap.clear_with(255)
                page.insert_image(fitz.Rect(30, 80, 565, 770), pixmap=pixmap)
        document.save(path)
    return str(path)


def test_pdf_page_limit_precedes_page_processing(tmp_path, monkeypatch):
    path = _pdf(tmp_path / "terms.pdf", pages=2)
    monkeypatch.setattr(pdf_extractor, "MAX_PDF_PAGES", 1)

    def unexpected_tables(*args):
        pytest.fail("The page count should be checked before reading tables.")

    monkeypatch.setattr(pdf_extractor, "_extract_tables", unexpected_tables)
    with pytest.raises(document_read_limits.DocumentReadLimit, match="1-page reading limit"):
        pdf_extractor.extract_pdf(path)


def test_pdf_ocr_budget_preserves_native_text_and_reports_unread_image(tmp_path, monkeypatch):
    path = _pdf(tmp_path / "scans.pdf", pages=2, scanned=True)
    # Letter-page rendering at the ordinary DPI costs about four million pixels.
    monkeypatch.setattr(pdf_extractor, "MAX_PDF_OCR_PIXELS", 5_000_000)
    calls = []

    def fake_ocr(page):
        calls.append(page.number)
        return "Budget contingency costs from the scanned chart $10,000."

    monkeypatch.setattr(pdf_extractor, "_ocr_page", fake_ocr)
    result = pdf_extractor.extract_pdf(path)

    assert calls == [0]
    assert [page["ocr_reading_limit"] for page in result.page_diagnostics] == [False, True]
    assert result.page_diagnostics[1]["image_text_unread"]
    assert "Project terms page 1" in result.text and "Project terms page 2" in result.text
    assert "scanned chart $10,000" in result.text
    assert result.images == []
    assert not (tmp_path / "images").exists()


def test_oversized_ocr_render_is_skipped_before_rasterization(tmp_path, monkeypatch):
    path = _pdf(tmp_path / "scans.pdf", scanned=True)
    monkeypatch.setattr(pdf_extractor, "MAX_OCR_RENDER_PIXELS", 1_000_000)

    def unexpected_ocr(*args):
        pytest.fail("The raster dimensions should be checked before OCR.")

    monkeypatch.setattr(pdf_extractor, "_ocr_page", unexpected_ocr)
    result = pdf_extractor.extract_pdf(path)
    assert result.page_diagnostics[0]["ocr_reading_limit"]
    assert "total construction costs $100,000" in result.text


def _workbook(path):
    workbook = openpyxl.Workbook()
    workbook.active.append(["Minimum investment", 50000])
    workbook.create_sheet("Costs").append(["Construction costs", 100000])
    workbook.save(path)
    workbook.close()
    return path


@pytest.mark.parametrize("cap", [
    "MAX_WORKBOOK_ARCHIVE_ENTRIES", "MAX_WORKBOOK_ENTRY_BYTES", "MAX_WORKBOOK_EXPANDED_BYTES",
])
def test_workbook_archive_limit_precedes_openpyxl(tmp_path, monkeypatch, cap):
    path = _workbook(tmp_path / "terms.xlsx")
    with zipfile.ZipFile(path) as archive:
        assert len(archive.infolist()) > 1
    monkeypatch.setattr(spreadsheet_extractor, cap, 1)

    def unexpected_parse(*args, **kwargs):
        pytest.fail("Archive admission should precede Excel parsing.")

    monkeypatch.setattr(openpyxl, "load_workbook", unexpected_parse)
    with pytest.raises(document_read_limits.DocumentReadLimit, match="workbook"):
        spreadsheet_extractor.extract_spreadsheet(str(path))


def test_workbook_combined_limit_and_ordinary_citations(tmp_path, monkeypatch):
    path = _workbook(tmp_path / "terms.xlsx")
    result = spreadsheet_extractor.extract_spreadsheet(str(path))
    assert "A1=Minimum investment | B1=50000" in result.text
    assert "A1=Construction costs | B1=100000" in result.text

    monkeypatch.setattr(spreadsheet_extractor, "MAX_WORKBOOK_CELL_SLOTS", 3)
    with pytest.raises(document_read_limits.DocumentReadLimit, match="combined reading limit"):
        spreadsheet_extractor.extract_spreadsheet(str(path))


def test_csv_multiline_record_limit_allows_typical_quoted_values(tmp_path, monkeypatch):
    path = tmp_path / "terms.csv"
    path.write_text('Term,Value\n"Project notes\nfollow-up",50000\n', encoding="utf-8")
    result = spreadsheet_extractor.extract_spreadsheet(str(path))
    assert "B2=50000" in result.text

    monkeypatch.setattr(spreadsheet_extractor, "MAX_CSV_RECORD_CHARS", 24)
    with pytest.raises(document_read_limits.DocumentReadLimit, match="CSV row exceeds"):
        spreadsheet_extractor.extract_spreadsheet(str(path))
