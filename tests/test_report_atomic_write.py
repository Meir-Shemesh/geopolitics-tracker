"""A daily report is written in one transaction, and a header row without
sections never counts as an existing report. Temp DB only - no API, no tracker.db."""
import sqlite3
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.common.db import init_db, insert_report, insert_report_section, link_section_article, report_exists, report_row_exists  # noqa: E402
from src.reporting import synthesize  # noqa: E402

D = "2026-10-13"


def make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def one_section(label="t"):
    return {"topic_label_he": label, "topic_label_en": label, "topic_label_de": label,
            "comparison_text_he": "x", "comparison_text_en": "x", "comparison_text_de": "x",
            "category": "security_conflict", "article_ids": []}


class ReportExistsTest(unittest.TestCase):
    def test_header_row_without_sections_is_not_a_report(self):
        conn = make_conn()
        insert_report(conn, D, "[]", created_at="t")
        self.assertTrue(report_row_exists(conn, D))
        self.assertFalse(report_exists(conn, D))

    def test_header_plus_section_is_a_report(self):
        conn = make_conn()
        insert_report(conn, D, "[]", created_at="t")
        insert_report_section(conn, D, "h", "e", "h", "e", "security_conflict", "t", "d", "d")
        self.assertTrue(report_exists(conn, D))


class AtomicWriteTest(unittest.TestCase):
    def test_failure_midway_leaves_nothing_behind(self):
        conn = make_conn()
        sections = [one_section("a"), one_section("b")]
        sections[1]["category"] = None  # NOT NULL violation on the SECOND section, after header + first section
        with self.assertRaises(sqlite3.IntegrityError):
            try:
                synthesize._write_report(conn, D, [], sections, [], set(), "t", None)
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        self.assertFalse(report_row_exists(conn, D))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM report_sections").fetchone()[0], 0)

    def test_success_writes_header_and_all_sections(self):
        conn = make_conn()
        synthesize._write_report(conn, D, [], [one_section("a"), one_section("b")], [], set(), "t", None)
        conn.commit()
        self.assertTrue(report_exists(conn, D))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM report_sections").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
