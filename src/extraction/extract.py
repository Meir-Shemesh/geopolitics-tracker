"""Extract raw text from downloaded PDFs (data/raw/) into data/processed/.

Reads files pending extraction from tracker.db (extraction_status='pending'),
extracts text per page with pdfplumber, and saves both a plain-text copy
(data/processed/extracted/<name>.txt) and per-page rows in extracted_pages.
No article segmentation or classification happens here - that's Analysis.
One-shot run - not a long-running daemon.
"""

import argparse
import json
import subprocess
import sys
import time
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

# Windows defaults stdout to the cp1252 console codepage even when redirected
# to a file, which raises UnicodeEncodeError on any print() containing a
# character outside it (e.g. Balkan/Slavic names) - fatal mid-run otherwise.
sys.stdout.reconfigure(encoding="utf-8")

EXTRACTED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed" / "extracted"
FAILED_PAGE_MARKER = "[EXTRACTION FAILED]"
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Per-file ceiling (PROJECT_LOG 4.130). A guard against a stuck file only: a legitimately heavy file
# (The Guardian UK, 87 MB / 212 pages) took 27 minutes on 2026-11-07, so this must stay well above that.
# A file over the ceiling is skipped, stays 'pending', and is retried by the next run's extract.
FILE_TIMEOUT_SECONDS = 2400
RESULT_PREFIX = "RESULT "
SKIP_LINE_PREFIX = "  SKIPPED (file timeout): "


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


def run_file_in_subprocess(file_id: int, timeout: float) -> dict:
    """Extract one file in a child process so a stuck file can be killed without killing the run.

    Returns {"status": "completed", "pages", "pages_failed"} | {"status": "failed", "error"} |
    {"status": "timeout"}. The child commits only when the whole file is done, so a killed child leaves
    the file 'pending' with no partial rows.
    """
    cmd = [sys.executable, "-m", "src.extraction.extract", "--file-id", str(file_id)]
    try:
        proc = subprocess.run(
            cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith(RESULT_PREFIX):
            return json.loads(line[len(RESULT_PREFIX):])
    return {"status": "failed", "error": f"child exit {proc.returncode}: {proc.stderr.strip()[-300:]}"}


def run_single_file(file_id: int) -> int:
    """Child entry point (--file-id): extract one file, print a RESULT line, never raise."""
    conn = get_connection()
    init_db(conn)
    row = conn.execute(
        "SELECT id, file_name, local_path FROM downloaded_files WHERE id = ?", (file_id,)
    ).fetchone()
    try:
        pages, failed = process_file(conn, row)
        # CPU seconds of this child process (user+kernel). Compared with the parent's wall time it separates a
        # machine that is slow because it is throttled/asleep (low CPU/wall) from a file that is simply heavy
        # (CPU/wall near 1). PROJECT_LOG 4.132 (Modern Standby investigation).
        result = {"status": "completed", "pages": pages, "pages_failed": failed,
                  "cpu_seconds": round(time.process_time(), 2)}
    except Exception as exc:
        set_extraction_result(conn, file_id, "failed", str(exc))
        result = {"status": "failed", "error": str(exc)}
    conn.close()
    print(RESULT_PREFIX + json.dumps(result), flush=True)
    return 0


def run(file_timeout: float = FILE_TIMEOUT_SECONDS, runner=run_file_in_subprocess) -> None:
    conn = get_connection()
    init_db(conn)

    pending = get_pending_extraction_files(conn)
    conn.close()

    files_completed = 0
    files_failed = 0
    files_skipped = 0
    total_pages = 0
    total_pages_failed = 0

    for file_row in pending:
        started = time.monotonic()
        result = runner(file_row["id"], file_timeout)
        elapsed = time.monotonic() - started

        if result["status"] == "timeout":
            files_skipped += 1
            print(
                f"{SKIP_LINE_PREFIX}{file_row['file_name']} (id {file_row['id']}) exceeded "
                f"{file_timeout:.0f}s - left 'pending', retried by the next run"
            )
            continue
        if result["status"] != "completed":
            files_failed += 1
            print(f"  failed: {file_row['file_name']} ({result.get('error')}) [{elapsed:.0f}s]")
            continue

        files_completed += 1
        total_pages += result["pages"]
        total_pages_failed += result["pages_failed"]
        note = f", {result['pages_failed']} page(s) failed" if result["pages_failed"] else ""
        cpu = result.get("cpu_seconds")
        cpu_note = f" [cpu {cpu:.0f}s, cpu/wall {cpu / max(elapsed, 0.001):.2f}]" if cpu is not None else ""
        print(f"  completed: {file_row['file_name']} ({result['pages']} page(s){note}, {elapsed:.0f}s){cpu_note}")

    summary = (
        f"\nExtraction: {files_completed} file(s) completed, {files_failed} file(s) failed, "
        f"{files_skipped} file(s) skipped (timeout), {total_pages} page(s) extracted in total"
    )
    if total_pages_failed:
        summary += f", {total_pages_failed} page(s) failed within completed files"
    print(summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file-id", type=int, help="child mode: extract this one file and print a RESULT line")
    parser.add_argument("--file-timeout", type=float, default=FILE_TIMEOUT_SECONDS, help="seconds per file")
    args = parser.parse_args()
    if args.file_id is not None:
        sys.exit(run_single_file(args.file_id))
    run(file_timeout=args.file_timeout)
