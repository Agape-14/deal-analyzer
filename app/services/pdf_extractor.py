import fitz  # PyMuPDF


def extract_text_from_pdf(file_path: str) -> tuple[str, int]:
    """Extract text from a PDF file. Returns (text, page_count)."""
    doc = fitz.open(file_path)
    page_count = len(doc)
    text_parts = []
    for page_num, page in enumerate(doc, 1):
        page_text = page.get_text()
        if page_text.strip():
            text_parts.append(f"--- Page {page_num} ---\n{page_text}")
    doc.close()
    return "\n\n".join(text_parts), page_count
