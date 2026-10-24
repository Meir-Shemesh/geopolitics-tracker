"""Tests for the first-scan report-date exception (CLAUDE.md, PROJECT_LOG 4.109) and the pdf_health_check
verdict split.

A file normally keeps the report_date of its download day. Only when its FIRST screening happens on a later
processing day (held back as SUSPECT, downloaded after that day's run, ...) does it move to the processing
day, once, with the original kept. Nothing here touches the real database.
"""

import sqlite3
import tempfile
import unittest
from datetime import timedelta, timezone
from pathlib import Path

from scripts.pdf_health_check import classify
from src.common import db

ISRAEL = timezone(timedelta(hours=3))


class ClaimReportDateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = sqlite3.connect(Path(self._tmp.name) / "test.db")
        self.conn.row_factory = sqlite3.Row
        db.init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def add_file(self, message_id: int, report_date: str | None, published_at: str = "2026-10-23T10:00:00+00:00") -> int:
        cursor = self.conn.execute(
            "INSERT INTO downloaded_files (channel, message_id, file_name, newspaper, published_at, downloaded_at, "
            "local_path, report_date) VALUES ('t', ?, ?, 'Economist', ?, '2026-10-23T12:26:00+00:00', '/x.pdf', ?)",
            (message_id, f"f{message_id}.pdf", published_at, report_date),
        )
        self.conn.commit()
        return cursor.lastrowid

    def screen_one_page(self, file_id: int) -> None:
        db.insert_page_screening(self.conn, file_id, 1, True, "r", "2026-10-24T13:00:00+00:00", "m")

    def row(self, file_id: int) -> sqlite3.Row:
        return self.conn.execute("SELECT * FROM downloaded_files WHERE id = ?", (file_id,)).fetchone()

    def test_screened_on_its_download_day_is_unchanged(self):
        file_id = self.add_file(1, "2026-10-23")
        self.assertIsNone(db.claim_report_date_on_first_scan(self.conn, file_id, "2026-10-23T13:00:00+00:00", ISRAEL))
        row = self.row(file_id)
        self.assertEqual(row["report_date"], "2026-10-23")
        self.assertIsNone(row["report_date_original"])
        self.assertIsNone(row["report_date_shifted_at"])

    def test_screened_on_a_later_day_moves_once_and_keeps_the_original(self):
        file_id = self.add_file(1, "2026-10-23")
        db.record_screening_hold(self.conn, file_id, "SUSPECT: test")
        shift = db.claim_report_date_on_first_scan(self.conn, file_id, "2026-10-24T13:00:00+00:00", ISRAEL)
        self.assertEqual((shift["original"], shift["new"], shift["hold_reason"]), ("2026-10-23", "2026-10-24", "SUSPECT: test"))
        row = self.row(file_id)
        self.assertEqual(row["report_date"], "2026-10-24")
        self.assertEqual(row["report_date_original"], "2026-10-23")
        self.assertEqual(row["report_date_shifted_at"], "2026-10-24T13:00:00+00:00")
        self.assertEqual([r["id"] for r in db.get_report_date_shifts(self.conn, "2026-10-24")], [file_id])

    def test_second_call_is_a_no_op_even_on_a_still_later_day(self):
        file_id = self.add_file(1, "2026-10-23")
        db.claim_report_date_on_first_scan(self.conn, file_id, "2026-10-24T13:00:00+00:00", ISRAEL)
        self.screen_one_page(file_id)  # the first page got its row: the date is now settled
        self.assertIsNone(db.claim_report_date_on_first_scan(self.conn, file_id, "2026-10-26T13:00:00+00:00", ISRAEL))
        self.assertEqual(self.row(file_id)["report_date"], "2026-10-24")

    def test_file_with_existing_screening_never_moves(self):
        file_id = self.add_file(1, "2026-10-23")
        self.screen_one_page(file_id)  # e.g. an interrupted run that screened part of the file yesterday
        self.assertIsNone(db.claim_report_date_on_first_scan(self.conn, file_id, "2026-10-25T13:00:00+00:00", ISRAEL))
        self.assertEqual(self.row(file_id)["report_date"], "2026-10-23")

    def test_cutoff_hour_keeps_a_run_that_crosses_midnight_on_its_own_day(self):
        file_id = self.add_file(1, "2026-10-24")
        # 00:30 Israel time on the 25th (21:30 UTC on the 24th) is still the 24th's run
        self.assertIsNone(db.claim_report_date_on_first_scan(self.conn, file_id, "2026-10-24T21:30:00+00:00", ISRAEL))
        self.assertEqual(self.row(file_id)["report_date"], "2026-10-24")
        # 03:00 Israel time is the next processing day
        shift = db.claim_report_date_on_first_scan(self.conn, file_id, "2026-10-25T00:00:00+00:00", ISRAEL)
        self.assertEqual(shift["new"], "2026-10-25")

    def test_legacy_row_without_report_date_uses_published_at_as_the_original(self):
        file_id = self.add_file(1, None, published_at="2026-10-20T09:00:00+00:00")
        shift = db.claim_report_date_on_first_scan(self.conn, file_id, "2026-10-24T13:00:00+00:00", ISRAEL)
        self.assertEqual((shift["original"], shift["new"]), ("2026-10-20", "2026-10-24"))

    def test_screen_run_claims_before_the_first_row_including_the_duplicate_copy_path(self):
        """Wiring check on src.analysis.screen.run(): a copied verdict (byte-identical duplicate) counts as a
        first scan too, so the duplicate's date moves exactly like a normally screened file."""
        from unittest import mock

        from src.analysis import screen

        canonical = self.add_file(1, "2026-10-24")
        duplicate = self.add_file(2, "2026-10-23")
        for fid in (canonical, duplicate):
            self.conn.execute(
                "INSERT INTO extracted_pages (file_id, page_number, raw_text, extracted_at) VALUES (?, 1, 'text', 'x')", (fid,)
            )
        self.screen_one_page(canonical)
        self.conn.commit()
        def fresh_connection():  # run() closes the connection it gets, so hand it its own
            conn = sqlite3.connect(Path(self._tmp.name) / "test.db")
            conn.row_factory = sqlite3.Row
            return conn

        with mock.patch.object(screen, "get_connection", side_effect=fresh_connection), \
                mock.patch.object(screen, "init_db"), \
                mock.patch.object(screen.anthropic, "Anthropic"), \
                mock.patch.object(screen, "load_dotenv"), \
                mock.patch.object(screen, "find_duplicate_canonicals", return_value={duplicate: canonical}), \
                mock.patch.object(screen, "claim_report_date_on_first_scan",
                                  wraps=lambda c, f: db.claim_report_date_on_first_scan(c, f, "2026-10-24T13:00:00+00:00", ISRAEL)):
            screen.run()
        self.assertEqual(self.row(duplicate)["report_date"], "2026-10-24")
        self.assertEqual(self.row(duplicate)["report_date_original"], "2026-10-23")
        self.assertEqual(self.row(canonical)["report_date"], "2026-10-24")  # untouched: already screened


class HealthVerdictTest(unittest.TestCase):
    def test_only_the_pdflib_signature_blocks(self):
        self.assertEqual(classify({"pdflib_signature": True, "text_image_signature": False}), "suspect")
        self.assertEqual(classify({"pdflib_signature": True, "text_image_signature": True}), "suspect")

    def test_the_page_zero_signature_alone_is_only_a_warning(self):
        self.assertEqual(classify({"pdflib_signature": False, "text_image_signature": True}), "warn")

    def test_clean_file_is_ok(self):
        self.assertEqual(classify({"pdflib_signature": False, "text_image_signature": False}), "ok")


if __name__ == "__main__":
    unittest.main()
