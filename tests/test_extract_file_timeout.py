"""extract.py's per-file timeout, per-file timing and the wrapper's skip notes (PROJECT_LOG 4.130).

No real PDFs and no tracker.db: the per-file runner is injected, the database is a temp file.
"""

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from scripts import daily_autorun
from src.common import db
from src.extraction import extract


def _make_db(tmp: str, names: list[str], report_date: str = "2026-11-07") -> Path:
    path = Path(tmp) / "t.db"
    conn = db.get_connection(path)
    db.init_db(conn)
    for i, name in enumerate(names, start=1):
        conn.execute(
            "INSERT INTO downloaded_files (id, channel, file_name, local_path, newspaper, downloaded_at, report_date, "
            "extraction_status, message_id, published_at) VALUES (?, 'demagazinesharing', ?, ?, 'Guardian', ?, ?, 'pending', ?, ?)",
            (i, name, f"x/{name}", "2026-11-07T13:00:00+00:00", report_date, i, "2026-11-07T10:00:00+00:00"),
        )
    conn.commit()
    conn.close()
    return path


def _run_extract(path: Path, runner, timeout=2400.0) -> str:
    buf = io.StringIO()
    with mock.patch.object(extract, "get_connection", lambda: db.get_connection(path)), redirect_stdout(buf):
        extract.run(file_timeout=timeout, runner=runner)
    return buf.getvalue()


class ExtractFileTimeoutTest(unittest.TestCase):
    def test_default_is_40_minutes(self):
        self.assertEqual(extract.FILE_TIMEOUT_SECONDS, 2400)

    def test_skipped_file_is_reported_and_the_rest_continue(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = _make_db(tmp, ["a.pdf", "slow.pdf", "c.pdf"])
            calls = []

            def runner(file_id, timeout):
                calls.append((file_id, timeout))
                if file_id == 2:
                    return {"status": "timeout"}
                return {"status": "completed", "pages": 10, "pages_failed": 0}

            out = _run_extract(path, runner, timeout=123.0)
        self.assertEqual(calls, [(1, 123.0), (2, 123.0), (3, 123.0)])
        self.assertIn("SKIPPED (file timeout): slow.pdf (id 2) exceeded 123s", out)
        self.assertIn("2 file(s) completed, 0 file(s) failed, 1 file(s) skipped (timeout), 20 page(s)", out)

    def test_completed_line_carries_the_page_count_and_seconds(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = _make_db(tmp, ["a.pdf"])
            out = _run_extract(path, lambda fid, t: {"status": "completed", "pages": 76, "pages_failed": 2})
        self.assertRegex(out, r"completed: a\.pdf \(76 page\(s\), 2 page\(s\) failed, \d+s\)")

    def test_failed_file_gets_a_line_with_its_time(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = _make_db(tmp, ["a.pdf"])
            out = _run_extract(path, lambda fid, t: {"status": "failed", "error": "bad pdf"})
        self.assertRegex(out, r"failed: a\.pdf \(bad pdf\) \[\d+s\]")
        self.assertIn("1 file(s) failed", out)

    def test_skipped_file_stays_pending_and_is_retried_next_run(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = _make_db(tmp, ["slow.pdf"])
            _run_extract(path, lambda fid, t: {"status": "timeout"})
            conn = db.get_connection(path)
            try:
                self.assertEqual([r["file_name"] for r in db.get_pending_extraction_files(conn)], ["slow.pdf"])
            finally:
                conn.close()

    def test_skipped_file_joins_the_next_days_report_on_first_scan(self):
        # The documented consequence: skipped today, extracted tomorrow, first screened tomorrow ->
        # report_date moves 2026-11-07 -> 2026-11-08 (REPORT_DATE_SHIFT), and nothing reopens a published report.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = _make_db(tmp, ["slow.pdf"])
            conn = db.get_connection(path)
            try:
                tomorrow = datetime(2026, 11, 8, 15, 0, tzinfo=timezone.utc).isoformat()
                shift = db.claim_report_date_on_first_scan(conn, 1, now=tomorrow, tz=timezone.utc)
            finally:
                conn.close()
        self.assertEqual((shift["original"], shift["new"]), ("2026-11-07", "2026-11-08"))

    def test_subprocess_timeout_maps_to_timeout_status(self):
        with mock.patch.object(extract.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 1)):
            self.assertEqual(extract.run_file_in_subprocess(5, 1), {"status": "timeout"})

    def test_subprocess_result_line_is_parsed(self):
        payload = {"status": "completed", "pages": 3, "pages_failed": 0}
        proc = subprocess.CompletedProcess([], 0, stdout="noise\nRESULT " + json.dumps(payload) + "\n", stderr="")
        with mock.patch.object(extract.subprocess, "run", return_value=proc):
            self.assertEqual(extract.run_file_in_subprocess(5, 1), payload)

    def test_subprocess_without_result_line_is_a_failure(self):
        proc = subprocess.CompletedProcess([], 1, stdout="", stderr="boom")
        with mock.patch.object(extract.subprocess, "run", return_value=proc):
            result = extract.run_file_in_subprocess(5, 1)
        self.assertEqual(result["status"], "failed")
        self.assertIn("boom", result["error"])


class WrapperExtractSkipTest(unittest.TestCase):
    def test_skip_notes_are_extracted_from_stdout(self):
        out = "  completed: a.pdf (3 page(s), 5s)\n  SKIPPED (file timeout): slow.pdf (id 2) exceeded 2400s - left 'pending'\n"
        self.assertEqual(
            daily_autorun.extract_skip_notes(out), ["slow.pdf (id 2) exceeded 2400s - left 'pending'"]
        )
        self.assertEqual(daily_autorun.extract_skip_notes(""), [])

    def test_timeouts_locked(self):
        self.assertEqual(daily_autorun.TIMEOUTS["extract"], 90 * 60)
        self.assertEqual(daily_autorun.TIMEOUTS["fetch"], 120 * 60)
        # the per-file ceiling must fit inside the step ceiling with room for the other files
        self.assertLess(extract.FILE_TIMEOUT_SECONDS, daily_autorun.TIMEOUTS["extract"])


if __name__ == "__main__":
    unittest.main()
