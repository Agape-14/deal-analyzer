"""Bind review evidence to a PDF table cell and isolate reading warnings."""

import re

from app.services.source_evidence import normalized_text, numeric_quote_error


def _quality(document):
    return (document.extraction_quality or {}) if document is not None else {}


def table_locators(document):
    return [
        {"page": table["page"], "table_index": table["table_index"],
         "column_labels": table["column_labels"], "row_numbers": [row["row"] for row in table["review_rows"]]}
        for table in (_quality(document).get("pdf_tables") or [])
    ]


def table_fact_evidence(fact, document):
    coordinates = (fact.source_table_index, fact.source_table_row, fact.source_table_column)
    if not any(coordinates):
        return None, {}, ""
    if not all(coordinates) or fact.source_page is None or fact.source_sheet or fact.source_cell:
        return None, {}, "A PDF table citation needs the page, table, row and column."
    index, row, column = coordinates
    table = next((table for table in (_quality(document).get("pdf_tables") or [])
                  if (table["page"], table["table_index"]) == (fact.source_page, index)), None)
    if table is None:
        return None, {}, "The cited PDF table could not be identified. Recheck the original page."
    rows = table["rows"]
    source_row = next((item["text"] for item in table["review_rows"] if item["row"] == row), "")
    if not source_row or row > len(rows) or column > len(rows[row - 1]):
        return None, {}, "The cited row or column could not be identified in the PDF table."
    cell = str(rows[row - 1][column - 1] or "").strip()
    excerpt = normalized_text(fact.source_excerpt)
    if not cell or excerpt not in normalized_text(source_row) or normalized_text(cell) not in excerpt:
        return None, {}, "Quote the cited value from its PDF table row and column."
    labels = table["column_labels"]
    return cell, {"source_table_index": index, "source_table_row": row, "source_table_column": column,
                  "source_column_label": labels[column - 1] if column <= len(labels) else None}, ""


def _matches_warning(fact, warning):
    if warning.get("page") != fact.source_page:
        return False
    if fact.source_table_index:
        if warning.get("table_index") is not None:
            return (warning.get("table_index"), warning.get("row"), warning.get("column")) == (
                fact.source_table_index, fact.source_table_row, fact.source_table_column)
    if not isinstance(fact.value, (int, float)):
        return False
    excerpt = normalized_text(fact.source_excerpt)
    row_text = normalized_text(warning.get("source_row"))
    row_label = normalized_text(warning.get("row_label"))
    column_label = normalized_text(warning.get("column_label"))
    complete_row = bool(row_text and row_text in excerpt)
    if not complete_row and not (row_label and row_label in excerpt):
        return False
    for token in (warning.get("native_token"), warning.get("corroborating_token")):
        token = normalized_text(token)
        if not token:
            continue
        pattern = r"(?<![\w.])" + re.escape(token) + r"(?![\w.])"
        if not re.search(pattern, excerpt):
            continue
        if not complete_row and column_label and len(re.findall(pattern, row_text)) > 1 and column_label not in excerpt:
            continue
        if not numeric_quote_error(fact.value, {"source_excerpt": token}, allow_workbook_ratio=False):
            return True
    return False


def table_number_warning(fact, document):
    warning = next((item for item in (_quality(document).get("numeric_diagnostics") or [])
                    if _matches_warning(fact, item)), None)
    if warning is None:
        return ""
    location = " · ".join(str(value) for value in (
        f"page {fact.source_page}", warning.get("row_label"), warning.get("column_label")) if value)
    return f"Readings differ or the amount is unclear at {location}. Check the original PDF before approving this value."
