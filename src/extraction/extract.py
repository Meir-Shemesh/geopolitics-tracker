"""Extract raw text from downloaded PDFs (data/raw/) into data/processed/.

Reads files pending extraction from tracker.db (extraction_status='pending'),
extracts text per page with pdfplumber, and saves both a plain-text copy
(data/processed/extracted/<name>.txt) and per-page rows in extracted_pages.
No article segmentation or classification happens here - that's Analysis.
One-shot run - not a long-running daemon.
"""

from datetime import datetime, timezone
from pathlib import Path

import pdfplumber

from src.common.db import (
    get_connection,
    get_pending_extraction_files,
    init_db,
    insert_extracted_page,
    set_extraction_result,
)

EXTRACTED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed" / "extracted"
FAILED_PAGE_MARKER = "[EXTRACTION FAILED]"


def extract_pdf_pages(pdf_path: Path) -> list[tuple[str, bool]]:
    """Return (raw_text, page_failed) per page.

    Raises if the PDF itself can't be opened (corrupt file etc.) - that is
    the only case that should fail the whole file. A page-level extraction
    error is caught here and recorded as a failed page instead.
    """
    pages: list[tuple[str, bool]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            try:
                pages.append((page.extract_text() or "", False))
            except Exception as exc:
                pages.append((f"{FAILED_PAGE_MARKER} {exc}", True))
    return pages


def write_text_copy(stem: str, pages: list[tuple[str, bool]]) -> Path:
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    text_path = EXTRACTED_DIR / f"{stem}.txt"
    blocks = [f"--- page {i} ---\n{text}" for i, (text, _failed) in enumerate(pages, start=1)]
    text_path.write_text("\n\n".join(blocks), encoding="utf-8")
    return text_path


def process_file(conn, file_row) -> tuple[int, int]:
    """Extract, save, and record one file. Returns (pages_extracted, pages_failed).

    Propagates an exception only when the file itself couldn't be opened.
    """
    pdf_path = Path(file_row["local_path"])
    pages = extract_pdf_pages(pdf_path)

    stem = Path(file_row["file_name"]).stem
    write_text_copy(stem, pages)

    now = datetime.now(timezone.utc).isoformat()
    pages_failed = 0
    for page_number, (text, failed) in enumerate(pages, start=1):
        insert_extracted_page(conn, file_row["id"], page_number, text, now)
        if failed:
            pages_failed += 1

    set_extraction_result(conn, file_row["id"], "completed")
    return len(pages), pages_failed


def run() -> None:
    conn = get_connection()
    init_db(conn)

    pending = get_pending_extraction_files(conn)

    files_completed = 0
    files_failed = 0
    total_pages = 0
    total_pages_failed = 0

    for file_row in pending:
        try:
            page_count, pages_failed = process_file(conn, file_row)
        except Exception as exc:
            set_extraction_result(conn, file_row["id"], "failed", str(exc))
            files_failed += 1
            print(f"  failed: {file_row['file_name']} ({exc})")
            continue

        files_completed += 1
        total_pages += page_count
        total_pages_failed += pages_failed
        note = f", {pages_failed} page(s) failed" if pages_failed else ""
        print(f"  completed: {file_row['file_name']} ({page_count} page(s){note})")

    conn.close()

    summary = (
        f"\nExtraction: {files_completed} file(s) completed, {files_failed} file(s) failed, "
        f"{total_pages} page(s) extracted in total"
    )
    if total_pages_failed:
        summary += f", {total_pages_failed} page(s) failed within completed files"
    print(summary)


if __name__ == "__main__":
    run()
