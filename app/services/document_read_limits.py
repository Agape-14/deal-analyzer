"""Shared admission limits for document reading and upload."""

import os


MAX_DOCUMENT_BYTES = 50 * 1024 * 1024


class DocumentReadLimit(ValueError):
    """A saved original exceeded the safe document reading budget."""


def check_input_size(file_path: str) -> None:
    if os.path.getsize(file_path) > MAX_DOCUMENT_BYTES:
        size_mb = MAX_DOCUMENT_BYTES // (1024 * 1024)
        raise DocumentReadLimit(f"The document exceeds the {size_mb} MB reading limit. Split it into smaller files.")
