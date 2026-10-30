"""Page-level duplicate detection in screen.py (PROJECT_LOG 4.113).

A page whose normalized text equals an already-screened page of the SAME newspaper - in this batch or anywhere in
the archive - copies that page's verdict and is never queued for analysis again. Nothing here touches the real
database or the API: screen_page() and the Anthropic client are mocked.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.analysis import screen
from src.common import db

LONG = "The prime minister said on Thursday that the sanctions on the northern ports would stay in place. " * 4
OTHER = "Opposition leaders demanded an inquiry into how the defence contract was awarded last spring. " * 4
assert len(LONG) > screen.MIN_DUPLICATE_PAGE_CHARS


class ScreenDuplicateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"
        self.conn = self.connect()
        db.init_db(self.conn)
        self.api_calls = []

        def fake_screen_page(client, raw_text, model=None, ref=None):
            self.api_calls.append(ref)
            return True, "fake verdict"

        patches = [
            mock.patch.object(screen, "get_connection", side_effect=self.connect),
            mock.patch.object(screen, "screen_page", side_effect=fake_screen_page),
            mock.patch.object(screen.anthropic, "Anthropic", return_value=mock.Mock()),
            mock.patch.object(screen, "load_dotenv"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def add_file(self, newspaper: str, message_id: int, local_path: str = "/missing.pdf") -> int:
        cursor = self.conn.execute(
            "INSERT INTO downloaded_files (channel, message_id, file_name, newspaper, published_at, downloaded_at, "
            "local_path, report_date) VALUES ('t', ?, ?, ?, '2026-10-16T10:00:00+00:00', '2026-10-16T12:00:00+00:00', ?, "
            "'2026-10-16')", (message_id, f"f{message_id}.pdf", newspaper, local_path),
        )
        self.conn.commit()
        return cursor.lastrowid

    def add_page(self, file_id: int, number: int, text: str) -> None:
        self.conn.execute(
            "INSERT INTO extracted_pages (file_id, page_number, raw_text, extracted_at) VALUES (?, ?, ?, 'x')",
            (file_id, number, text),
        )
        self.conn.commit()

    def screened(self, file_id: int, number: int = 1) -> sqlite3.Row:
        conn = self.connect()
        try:
            return conn.execute(
                "SELECT * FROM page_screening WHERE file_id = ? AND page_number = ?", (file_id, number)
            ).fetchone()
        finally:
            conn.close()

    def run_screen(self) -> None:
        with mock.patch("builtins.print"):
            screen.run()

    def screen_first_then_second(self, first_text: str, second_text: str, newspapers=("Los Angeles Times", "Los Angeles Times")):
        """First file screened by an earlier run (an earlier day), second file arrives later."""
        a = self.add_file(newspapers[0], 1)
        self.add_page(a, 1, first_text)
        self.run_screen()
        b = self.add_file(newspapers[1], 2)
        self.add_page(b, 1, second_text)
        self.api_calls.clear()
        self.run_screen()
        return a, b

    # --- the cases -------------------------------------------------------------------------------------------

    def test_cross_day_duplicate_copies_the_verdict_and_is_not_queued_for_analysis(self):
        # LA Times_1610.pdf vs LA Times_1710.pdf: 32 of 32 pages identical, a day apart
        a, b = self.screen_first_then_second(LONG, LONG)
        self.assertEqual(self.api_calls, [])  # the second page never reached the API
        first, second = self.screened(a), self.screened(b)
        self.assertEqual(first["analysis_status"], "pending")  # the original is still analyzed
        self.assertEqual(second["is_relevant"], 1)
        self.assertEqual(second["analysis_status"], screen.SKIPPED_DUPLICATE)
        self.assertTrue(second["model_used"].startswith("none (skipped - duplicate text"))
        conn = self.connect()
        pending = db.get_pages_pending_analysis(conn)
        conn.close()
        self.assertEqual([(r["file_id"], r["page_number"]) for r in pending], [(a, 1)])

    def test_whitespace_and_case_differences_still_match(self):
        a, b = self.screen_first_then_second(LONG, "  " + LONG.upper().replace(" ", "\n ") + "  ")
        self.assertEqual(self.api_calls, [])
        self.assertEqual(self.screened(b)["analysis_status"], screen.SKIPPED_DUPLICATE)

    def test_different_text_is_screened_normally(self):
        a, b = self.screen_first_then_second(LONG, OTHER)
        self.assertEqual(self.api_calls, [f"{b}:1"])
        self.assertEqual(self.screened(b)["analysis_status"], "pending")

    def test_a_one_word_difference_is_not_a_duplicate(self):
        a, b = self.screen_first_then_second(LONG, LONG.replace("Thursday", "Friday", 1))
        self.assertEqual(self.api_calls, [f"{b}:1"])

    def test_short_pages_are_never_matched(self):
        short = "Crossword solutions and a weather map."
        a, b = self.screen_first_then_second(short, short)
        self.assertEqual(self.api_calls, [f"{b}:1"])
        self.assertEqual(self.screened(b)["analysis_status"], "pending")

    def test_the_same_text_in_another_newspaper_is_not_a_duplicate(self):
        a, b = self.screen_first_then_second(LONG, LONG, newspapers=("Guardian", "Daily Telegraph"))
        self.assertEqual(self.api_calls, [f"{b}:1"])

    def test_a_non_relevant_original_gives_a_non_relevant_copy_with_no_skip_marker(self):
        a = self.add_file("Economist", 1)
        self.add_page(a, 1, LONG)
        with mock.patch.object(screen, "screen_page", return_value=(False, "no")):
            self.run_screen()
        b = self.add_file("Economist", 2)
        self.add_page(b, 1, LONG)
        self.run_screen()
        copy = self.screened(b)
        self.assertEqual((copy["is_relevant"], copy["analysis_status"]), (0, "pending"))

    def test_both_copies_in_the_same_batch_only_the_first_is_screened(self):
        a = self.add_file("Der Spiegel", 1)
        b = self.add_file("Der Spiegel", 2)
        for f in (a, b):
            self.add_page(f, 1, LONG)
            self.add_page(f, 2, OTHER)
        self.run_screen()
        self.assertEqual(self.api_calls, [f"{a}:1", f"{a}:2"])
        self.assertEqual({self.screened(b, n)["analysis_status"] for n in (1, 2)}, {screen.SKIPPED_DUPLICATE})
        self.assertEqual({self.screened(a, n)["analysis_status"] for n in (1, 2)}, {"pending"})

    def test_byte_identical_files_no_longer_queue_their_relevant_pages_for_analysis(self):
        # the file-level SHA path copied the verdict but left the page 'pending': the 2026-10-30 Economist waste
        path_a, path_b = Path(self._tmp.name) / "a.pdf", Path(self._tmp.name) / "b.pdf"
        path_a.write_bytes(b"same bytes")
        path_b.write_bytes(b"same bytes")
        a = self.add_file("Economist", 1, str(path_a))
        b = self.add_file("Economist", 2, str(path_b))
        for f in (a, b):
            self.add_page(f, 1, "short page")  # too short for the text check: only the file-level path can match
        self.run_screen()
        self.assertEqual(self.api_calls, [f"{a}:1"])
        self.assertEqual(self.screened(b)["analysis_status"], screen.SKIPPED_DUPLICATE)

    def test_hashes_are_filled_once_and_short_pages_get_the_empty_marker(self):
        a = self.add_file("Economist", 1)
        self.add_page(a, 1, LONG)
        self.add_page(a, 2, "tiny")
        self.assertEqual(screen.ensure_text_hashes(self.conn), 2)
        self.assertEqual(screen.ensure_text_hashes(self.conn), 0)
        rows = {r["page_number"]: r["text_hash"] for r in self.conn.execute("SELECT page_number, text_hash FROM extracted_pages")}
        self.assertEqual(rows[1], screen.page_text_hash(LONG))
        self.assertEqual(rows[2], "")


if __name__ == "__main__":
    unittest.main()
