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
