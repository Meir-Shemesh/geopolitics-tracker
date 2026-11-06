"""analyze.py: the operator skip list, the one-transaction-per-page write (PROJECT_LOG 4.113) and the failed-page
record (PROJECT_LOG 4.128).

The skip list is a file with one file_id per line, re-read whenever it changes, checked at the top of every page
iteration. The page write is a single transaction. Nothing here touches the real database or the API.
"""

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
import unittest
from pathlib import Path
from unittest import mock

from src.analysis import analyze
from src.common import db


def article(headline="Sanctions debate"):
    return {
        "headline": headline, "author": "A. Writer", "region_topic": "Sanctions", "stance_summary": "Argues for caution.",
        "key_excerpt": "We should wait.", "country_codes": ["US", "RU"], "conflict_zones": [],
    }


class ParseSkipFileTest(unittest.TestCase):
    def test_ids_comments_blank_lines_and_junk(self):
        ids, bad = analyze.parse_skip_file_ids("557  # Spiegel duplicate\n\n# only a comment\n558\n558\nabc\n12x\n")
        self.assertEqual(ids, {557, 558})
        self.assertEqual(bad, ["abc", "12x"])

    def test_empty(self):
        self.assertEqual(analyze.parse_skip_file_ids(""), (set(), []))


class AnalyzeRunTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"
        self.skip_path = Path(self._tmp.name) / "skip_files.txt"
        self.flag_dir = Path(self._tmp.name) / "review_flags"
        self._opened: list[sqlite3.Connection] = []
        self.conn = self.connect()
        db.init_db(self.conn)
        self.analyzed: list[str] = []
        self.on_analyze = None

        def fake_analyze_page(client, newspaper, raw_text, is_letters_page_=False, ref=None):
            self.analyzed.append(ref)
            if self.on_analyze:
                self.on_analyze(ref)
            return [article()]

        patches = [
            mock.patch.object(analyze, "get_connection", side_effect=self.connect),
            mock.patch.object(analyze, "analyze_page", side_effect=fake_analyze_page),
            mock.patch.object(analyze.anthropic, "Anthropic", return_value=mock.Mock()),
            mock.patch.object(analyze, "load_dotenv"),
            mock.patch.object(analyze, "SKIP_FILES_PATH", self.skip_path),
            mock.patch.object(analyze, "FAILED_PAGES_DIR", self.flag_dir),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self) -> None:
        for conn in self._opened:  # a run that raised on purpose never reached its own conn.close()
            conn.close()
        self._tmp.cleanup()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        self._opened.append(conn)
        return conn

    def add_file_with_pages(self, message_id: int, pages: int = 3, newspaper: str = "Economist") -> int:
        cursor = self.conn.execute(
            "INSERT INTO downloaded_files (channel, message_id, file_name, newspaper, published_at, downloaded_at, "
            "local_path) VALUES ('t', ?, ?, ?, '2026-10-30T10:00:00+00:00', '2026-10-30T12:00:00+00:00', '/x.pdf')",
            (message_id, f"f{message_id}.pdf", newspaper),
        )
        file_id = cursor.lastrowid
        for n in range(1, pages + 1):
            self.conn.execute(
                "INSERT INTO extracted_pages (file_id, page_number, raw_text, extracted_at) VALUES (?, ?, 'page text', 'x')",
                (file_id, n),
            )
            db.insert_page_screening(self.conn, file_id, n, True, "r", "2026-10-30T13:00:00+00:00", "m")
        self.conn.commit()
        return file_id

    def run_analyze(self) -> None:
        with mock.patch("builtins.print"):
            analyze.run()

    def run_analyze_output(self) -> str:
        with mock.patch("builtins.print") as printed:
            analyze.run()
        return "\n".join(" ".join(str(a) for a in call.args) for call in printed.call_args_list)

    def status(self, file_id: int) -> list[str]:
        conn = self.connect()
        try:
            return [r[0] for r in conn.execute(
                "SELECT analysis_status FROM page_screening WHERE file_id = ? ORDER BY page_number", (file_id,))]
        finally:
            conn.close()

    def count(self, table: str) -> int:
        conn = self.connect()
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            conn.close()

    # --- skip list ---------------------------------------------------------------------------------------

    def test_a_listed_file_is_not_analyzed_and_stays_pending(self):
        a, b = self.add_file_with_pages(1), self.add_file_with_pages(2)
        self.skip_path.write_text(f"{b}  # duplicate of {a}\n", encoding="utf-8")
        self.run_analyze()
        self.assertEqual(self.analyzed, [f"{a}:1", f"{a}:2", f"{a}:3"])
        self.assertEqual(self.status(a), ["completed"] * 3)
        self.assertEqual(self.status(b), ["pending"] * 3)
        self.assertEqual(self.count("articles"), 3)

    def test_removing_the_line_lets_a_later_run_analyze_the_file(self):
        a = self.add_file_with_pages(1)
        self.skip_path.write_text(str(a), encoding="utf-8")
        self.run_analyze()
        self.assertEqual(self.analyzed, [])
        self.skip_path.write_text("", encoding="utf-8")
        self.run_analyze()
        self.assertEqual(len(self.analyzed), 3)

    def test_a_line_added_while_the_run_is_going_takes_effect_on_the_next_page(self):
        a = self.add_file_with_pages(1, pages=4)

        def add_to_skip_list(ref):
            if ref == f"{a}:1":
                self.skip_path.write_text(f"{a}\n", encoding="utf-8")

        self.on_analyze = add_to_skip_list
        self.run_analyze()
        self.assertEqual(self.analyzed, [f"{a}:1"])  # pages 2-4 were skipped mid-run
        self.assertEqual(self.status(a), ["completed", "pending", "pending", "pending"])

    def test_a_missing_skip_file_changes_nothing(self):
        a = self.add_file_with_pages(1, pages=2)
        self.run_analyze()
        self.assertEqual(len(self.analyzed), 2)

    def test_an_unreadable_skip_file_never_stops_the_run(self):
        a = self.add_file_with_pages(1, pages=2)
        self.skip_path.mkdir()  # a directory where the file should be: read_text raises
        self.run_analyze()
        self.assertEqual(len(self.analyzed), 2)

    def test_junk_lines_are_ignored_and_valid_ones_still_apply(self):
        a, b = self.add_file_with_pages(1, pages=1), self.add_file_with_pages(2, pages=1)
        self.skip_path.write_text(f"not-a-number\n{b}\n", encoding="utf-8")
        self.run_analyze()
        self.assertEqual(self.analyzed, [f"{a}:1"])

    # --- one transaction per page ------------------------------------------------------------------------

    def test_a_normal_page_commits_articles_links_and_status_together(self):
        a = self.add_file_with_pages(1, pages=1)
        self.run_analyze()
        self.assertEqual(self.count("articles"), 1)
        self.assertEqual(self.count("article_countries"), 2)
        self.assertEqual(self.status(a), ["completed"])

    def test_a_failure_in_the_middle_of_a_page_leaves_nothing_behind(self):
        a = self.add_file_with_pages(1, pages=1)
        two = lambda *args, **kwargs: [article("First"), article("Second")]
        calls = {"n": 0}
        real = db.insert_article_countries

        def explode_on_second_article(conn, article_id, codes, commit=True):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("disk full")
            return real(conn, article_id, codes, commit=commit)

        with mock.patch.object(analyze, "analyze_page", side_effect=two), \
                mock.patch.object(analyze, "insert_article_countries", side_effect=explode_on_second_article):
            with self.assertRaises(RuntimeError):
                self.run_analyze()
        self.assertEqual(self.count("articles"), 0)  # not even the first article of the page survived
        self.assertEqual(self.count("article_countries"), 0)
        self.assertEqual(self.status(a), ["pending"])
        self.run_analyze()  # a clean retry inserts the page once
        self.assertEqual(self.count("articles"), 1)

    # --- failed-page record (4.128) ------------------------------------------------------------------------

    def fail_page(self, file_id: int, page: int, exc: Exception) -> None:
        def raise_on(ref):
            if ref == f"{file_id}:{page}":
                raise exc
        self.on_analyze = raise_on

    def test_failed_pages_are_listed_in_the_summary_and_recorded(self):
        a = self.add_file_with_pages(1, pages=3, newspaper="Der Spiegel")
        self.fail_page(a, 2, TimeoutError("request timed out\nafter 60s"))
        out = self.run_analyze_output()
        self.assertEqual(self.status(a), ["completed", "pending", "completed"])  # behaviour unchanged
        self.assertIn("Analysis: 2 page(s) analyzed, 1 page(s) failed", out)
        tail = out.split("Analysis: ", 1)[1]  # the lines the daily log's tail keeps
        self.assertIn("Failed pages (1)", tail)
        self.assertIn(f"file_id={a} page=2 (Der Spiegel) TimeoutError: request timed out after 60s", tail)
        files = list(self.flag_dir.glob("*.analyze_failed.json"))
        self.assertEqual(len(files), 1)
        self.assertIn(files[0].name, tail)
        record = json.loads(files[0].read_text(encoding="utf-8"))
        failed = record["runs"][0]["failed_pages"]
        self.assertEqual(failed, [{
            "file_id": a, "page_number": 2, "newspaper": "Der Spiegel",
            "error_type": "TimeoutError", "error": "request timed out after 60s",
        }])

    def test_a_failed_page_is_retried_by_the_next_run_exactly_as_before(self):
        a = self.add_file_with_pages(1, pages=2)
        self.fail_page(a, 1, RuntimeError("boom"))
        self.run_analyze_output()
        self.on_analyze = None
        out = self.run_analyze_output()
        self.assertEqual(self.status(a), ["completed", "completed"])
        self.assertEqual(self.count("articles"), 2)
        self.assertNotIn("Failed pages", out)
        self.assertEqual(len(list(self.flag_dir.glob("*.analyze_failed.json"))), 1)  # the earlier record stays

    def test_no_failures_means_no_record_and_no_failed_section(self):
        self.add_file_with_pages(1, pages=2)
        out = self.run_analyze_output()
        self.assertNotIn("Failed pages", out)
        self.assertFalse(self.flag_dir.exists())

    def test_a_record_that_cannot_be_written_never_stops_the_run(self):
        a = self.add_file_with_pages(1, pages=3)
        self.fail_page(a, 1, RuntimeError("boom"))
        self.flag_dir.write_text("a file where the directory should be", encoding="utf-8")
        out = self.run_analyze_output()
        self.assertEqual(self.status(a), ["pending", "completed", "completed"])
        self.assertIn("could not write the failed-pages record", out)
        self.assertIn("Failed pages (1)", out)  # the summary still lists the page

    def test_a_failure_while_describing_a_page_never_stops_the_run(self):
        a = self.add_file_with_pages(1, pages=2)
        self.fail_page(a, 1, RuntimeError("boom"))
        with mock.patch.object(analyze, "describe_failure", side_effect=KeyError("x")):
            out = self.run_analyze_output()
        self.assertEqual(self.status(a), ["pending", "completed"])
        self.assertIn("1 page(s) failed", out)


class FailedPagesRecordTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "flags"
        self.page = {"file_id": 7, "page_number": 3, "newspaper": "Economist"}

    def test_describe_failure_collapses_whitespace_and_truncates(self):
        entry = analyze.describe_failure(self.page, ValueError("line one\n\n  line two " + "x" * 500))
        self.assertEqual(entry["error_type"], "ValueError")
        self.assertTrue(entry["error"].startswith("line one line two xxx"))
        self.assertEqual(len(entry["error"]), analyze.FAILED_ERROR_MESSAGE_LIMIT)
        self.assertEqual((entry["file_id"], entry["page_number"], entry["newspaper"]), (7, 3, "Economist"))

    def test_nothing_is_written_for_an_empty_list(self):
        self.assertIsNone(analyze.write_failed_pages_record([], flag_dir=self.dir))
        self.assertFalse(self.dir.exists())

    def test_runs_on_the_same_day_append(self):
        first = analyze.describe_failure(self.page, RuntimeError("one"))
        second = analyze.describe_failure(self.page, RuntimeError("two"))
        t1 = datetime(2026, 11, 6, 16, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 11, 6, 20, 0, tzinfo=timezone.utc)
        path = analyze.write_failed_pages_record([first], flag_dir=self.dir, now=t1)
        self.assertEqual(path, analyze.write_failed_pages_record([second], flag_dir=self.dir, now=t2))
        self.assertEqual(path.name, "2026-11-06.analyze_failed.json")
        runs = json.loads(path.read_text(encoding="utf-8"))["runs"]
        self.assertEqual([r["failed_pages"][0]["error"] for r in runs], ["one", "two"])

    def test_an_unreadable_earlier_file_is_replaced_not_fatal(self):
        self.dir.mkdir()
        now = datetime(2026, 11, 6, 16, 0, tzinfo=timezone.utc)
        (self.dir / "2026-11-06.analyze_failed.json").write_text("{not json", encoding="utf-8")
        entry = analyze.describe_failure(self.page, RuntimeError("x"))
        path = analyze.write_failed_pages_record([entry], flag_dir=self.dir, now=now)
        self.assertEqual(len(json.loads(path.read_text(encoding="utf-8"))["runs"]), 1)

    def test_format_lines(self):
        entry = analyze.describe_failure(self.page, RuntimeError("bad json"))
        self.assertEqual(
            analyze.format_failed_pages([entry]),
            ["  failed page: file_id=7 page=3 (Economist) RuntimeError: bad json"],
        )


if __name__ == "__main__":
    unittest.main()
