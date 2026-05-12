"""Spreadsheet extraction service for deal underwriting files."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from typing import Any


MAX_SHEETS = 20
MAX_ROWS_PER_SHEET = 150
MAX_COLS_PER_SHEET = 40
MAX_CELL_PROVENANCE = 2000


@dataclass
class SpreadsheetExtractionResult:
    text: str = ""
    page_count: int = 0
    ocr_page_count: int = 0
    tables: list[dict] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)
    cells: list[dict] = field(default_factory=list)
    page_diagnostics: list[dict] = field(default_factory=list)
    quality_score: int = 100


def extract_spreadsheet(file_path: str) -> SpreadsheetExtractionResult:
    ext = os.path.splitext(file_path)[1].lower()
    if ext in {".xlsx", ".xlsm"}:
        return _extract_xlsx(file_path)
    if ext == ".xls":
        return _extract_xls(file_path)
    if ext == ".csv":
        return _extract_csv(file_path)

    result = SpreadsheetExtractionResult()
    result.text = f"[Unsupported spreadsheet type: {ext or 'unknown'}]"
    result.quality_score = 0
    return result


def _extract_xlsx(file_path: str) -> SpreadsheetExtractionResult:
    from openpyxl import load_workbook

    result = SpreadsheetExtractionResult()
    wb = load_workbook(file_path, data_only=True, read_only=True)
    formula_wb = load_workbook(file_path, data_only=False, read_only=True)
    sheet_names = list(wb.sheetnames)[:MAX_SHEETS]

    text_parts: list[str] = []
    try:
        for sheet_index, sheet_name in enumerate(sheet_names, 1):
            ws = wb[sheet_name]
            formula_ws = formula_wb[sheet_name] if sheet_name in formula_wb.sheetnames else None
            rows, table_rows, cells = _worksheet_rows(ws, formula_ws=formula_ws)
            result.cells.extend(cells)
            result.page_diagnostics.append(
                {"page": sheet_index, "source": "spreadsheet", "chars": sum(len(r) for r in rows)}
            )
            if table_rows:
                result.tables.append({"sheet": sheet_name, "rows": table_rows})
            text_parts.append(_render_sheet(sheet_name, rows))
    finally:
        wb.close()
        formula_wb.close()

    result.page_count = len(sheet_names)
    result.text = "\n\n".join(part for part in text_parts if part.strip())
    result.quality_score = 100 if result.text.strip() else 0
    return result


def _extract_xls(file_path: str) -> SpreadsheetExtractionResult:
    result = SpreadsheetExtractionResult()
    try:
        import xlrd
    except ImportError:
        result.text = "[Legacy .xls support requires xlrd.]"
        result.quality_score = 0
        return result

    book = xlrd.open_workbook(file_path)
    text_parts: list[str] = []
    sheet_count = min(book.nsheets, MAX_SHEETS)
    for sheet_index in range(sheet_count):
        sheet = book.sheet_by_index(sheet_index)
        rows: list[str] = []
        table_rows: list[list[Any]] = []
        max_rows = min(sheet.nrows, MAX_ROWS_PER_SHEET)
        max_cols = min(sheet.ncols, MAX_COLS_PER_SHEET)
        for row_idx in range(max_rows):
            values = [_clean_cell(sheet.cell_value(row_idx, col_idx)) for col_idx in range(max_cols)]
            if not any(v != "" for v in values):
                continue
            table_rows.append(values)
            for col_idx, value in enumerate(values):
                if value != "" and len(result.cells) < MAX_CELL_PROVENANCE:
                    result.cells.append(
                        {
                            "sheet": sheet.name,
                            "cell": f"R{row_idx + 1}C{col_idx + 1}",
                            "value": value,
                        }
                    )
            rows.append("\t".join(str(v) for v in values))
        if table_rows:
            result.tables.append({"sheet": sheet.name, "rows": table_rows})
        result.page_diagnostics.append(
            {"page": sheet_index + 1, "source": "spreadsheet", "chars": sum(len(r) for r in rows)}
        )
        text_parts.append(_render_sheet(sheet.name, rows))

    result.page_count = sheet_count
    result.text = "\n\n".join(part for part in text_parts if part.strip())
    result.quality_score = 100 if result.text.strip() else 0
    return result


def _extract_csv(file_path: str) -> SpreadsheetExtractionResult:
    result = SpreadsheetExtractionResult(page_count=1)
    rows: list[str] = []
    table_rows: list[list[str]] = []
    with open(file_path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        reader = csv.reader(fh)
        for idx, row in enumerate(reader):
            if idx >= MAX_ROWS_PER_SHEET:
                break
            trimmed = row[:MAX_COLS_PER_SHEET]
            if not any(cell.strip() for cell in trimmed):
                continue
            table_rows.append(trimmed)
            for col_idx, value in enumerate(trimmed):
                if value.strip() and len(result.cells) < MAX_CELL_PROVENANCE:
                    result.cells.append(
                        {
                            "sheet": "CSV",
                            "cell": f"R{idx + 1}C{col_idx + 1}",
                            "value": value,
                        }
                    )
            rows.append("\t".join(trimmed))
    if table_rows:
        result.tables.append({"sheet": "CSV", "rows": table_rows})
    result.page_diagnostics.append({"page": 1, "source": "spreadsheet", "chars": sum(len(r) for r in rows)})
    result.text = _render_sheet(os.path.basename(file_path), rows)
    result.quality_score = 100 if result.text.strip() else 0
    return result


def _worksheet_rows(ws, *, formula_ws=None) -> tuple[list[str], list[list[Any]], list[dict]]:
    from openpyxl.utils import get_column_letter

    rows: list[str] = []
    table_rows: list[list[Any]] = []
    cells: list[dict] = []
    max_row = min(ws.max_row or 0, MAX_ROWS_PER_SHEET)
    max_col = min(ws.max_column or 0, MAX_COLS_PER_SHEET)

    for row_idx in range(1, max_row + 1):
        row_values: list[str] = []
        raw_values: list[Any] = []
        for col_idx in range(1, max_col + 1):
            value = ws.cell(row=row_idx, column=col_idx).value
            formula_value = formula_ws.cell(row=row_idx, column=col_idx).value if formula_ws else None
            rendered = _render_cell(value)
            row_values.append(rendered)
            raw_values.append(value)
            formula = formula_value if isinstance(formula_value, str) and formula_value.startswith("=") else None
            if rendered and len(cells) < MAX_CELL_PROVENANCE:
                item = {
                    "sheet": ws.title,
                    "cell": f"{get_column_letter(col_idx)}{row_idx}",
                    "value": rendered,
                }
                if formula:
                    item["formula"] = formula
                cells.append(item)
        if not any(v != "" for v in row_values):
            continue
        table_rows.append(raw_values)
        rows.append("\t".join(row_values))

    return rows, table_rows, cells


def _render_sheet(sheet_name: str, rows: list[str]) -> str:
    if not rows:
        return f"--- Sheet: {sheet_name} ---\n[No readable cells found]"
    return f"--- Sheet: {sheet_name} ---\n" + "\n".join(rows)


def _render_cell(value: Any) -> str:
    return str(_clean_cell(value))


def _clean_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float):
        return round(value, 6)
    return value
