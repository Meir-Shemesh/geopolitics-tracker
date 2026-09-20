"""Tests for the report-date rule (CLAUDE.md, "שיוך מאמר לדוח"; PROJECT_LOG 4.43/4.44).

An article belongs to the report of the local calendar day on which the pipeline downloaded its
file (downloaded_files.report_date), not to the Telegram upload day (published_at). Rows that
predate the rule have report_date NULL and keep the legacy meaning, date(published_at).

Run from the project root:  python -m unittest discover -s tests -v
No real database is touched: every test builds a temporary one.
"""

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.common import db

ISRAEL = timezone(timedelta(hours=3))  # fixed offset: no dependency on tzdata or the host's timezone
SRC_DIR = Path(db.__file__).resolve().parents[1]


class TempDbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = sqlite3.connect(Path(self._tmp.name) / "test.db")
        self.conn.row_factory = sqlite3.Row
        db.init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()  # Windows cannot delete an open sqlite file
        self._tmp.cleanup()

    def add_file(self, message_id: int, newspaper: str, published_at: str, report_date: str | None) -> int:
        """Insert a downloaded_files row directly, so report_date is controlled (None = legacy row)."""
        cursor = self.conn.execute(
            "INSERT INTO downloaded_files (channel, message_id, file_name, newspaper, published_at, "
            "downloaded_at, local_path, report_date) VALUES ('test', ?, ?, ?, ?, ?, '/tmp/x.pdf', ?)",
            (message_id, f"file_{message_id}.pdf", newspaper, published_at, published_at, report_date),
        )
        self.conn.commit()
        return cursor.lastrowid

    def add_article(self, file_id: int, newspaper: str) -> int:
        return db.insert_article(
            self.conn, file_id, 1, newspaper, "en", f"headline {file_id}", "", "topic", "stance", "excerpt",
            "2026-09-20T10:00:00+00:00",
        )


class ReportDateForDownloadTest(unittest.TestCase):
    def test_uses_the_calendar_day_in_the_given_timezone(self):
        # 22:30 UTC is 01:30 the next day in Israel: the pipeline run belongs to the local day.
        self.assertEqual(db.report_date_for_download("2026-09-19T22:30:00+00:00", ISRAEL), "2026-09-20")
        self.assertEqual(db.report_date_for_download("2026-09-19T22:30:00+00:00", timezone.utc), "2026-09-19")

    def test_backlog_download_lands_on_the_download_day(self):
        self.assertEqual(db.report_date_for_download("2026-09-21T12:00:00+00:00", ISRAEL), "2026-09-21")

    def test_accepts_the_timestamp_format_fetch_writes(self):
        # fetch.py stores datetime.now(timezone.utc).isoformat(): microseconds and a +00:00 suffix.
        self.assertEqual(db.report_date_for_download("2026-09-19T17:42:13.167901+00:00", ISRAEL), "2026-09-19")

    def test_default_timezone_is_the_system_local_one(self):
        stamp = "2026-09-19T22:30:00+00:00"
        expected = datetime.fromisoformat(stamp).astimezone().date().isoformat()
        self.assertEqual(db.report_date_for_download(stamp), expected)


class MarkDownloadedTest(TempDbTestCase):
    def test_stores_the_download_day_not_the_upload_day(self):
        with mock.patch.object(db, "report_date_for_download", return_value="2026-09-20") as helper:
            db.mark_downloaded(
                self.conn, "test", 1, "TE-2026-09-19-PDF WEB.pdf", "Economist",
                "2026-09-17T23:09:38+00:00", "2026-09-20T05:00:00+00:00", "/tmp/x.pdf",
            )
        helper.assert_called_once_with("2026-09-20T05:00:00+00:00")
        row = self.conn.execute("SELECT published_at, report_date FROM downloaded_files").fetchone()
        self.assertEqual(row["report_date"], "2026-09-20")
        self.assertTrue(row["published_at"].startswith("2026-09-17"))  # upload time is still recorded, untouched


class SchemaMigrationTest(TempDbTestCase):
    def test_column_is_added_to_an_existing_db_and_old_rows_stay_null(self):
        self.conn.execute("ALTER TABLE downloaded_files DROP COLUMN report_date")  # simulate a pre-rule database
        self.conn.execute(
            "INSERT INTO downloaded_files (channel, message_id, file_name, newspaper, published_at, "
            "downloaded_at, local_path) VALUES ('test', 1, 'old.pdf', 'Guardian', "
            "'2026-09-17T10:00:00+00:00', '2026-09-17T11:00:00+00:00', '/tmp/old.pdf')"
        )
        self.conn.commit()
        columns = [r["name"] for r in self.conn.execute("PRAGMA table_info(downloaded_files)")]
        self.assertNotIn("report_date", columns)

        db.init_db(self.conn)  # what every pipeline run does

        columns = [r["name"] for r in self.conn.execute("PRAGMA table_info(downloaded_files)")]
        self.assertIn("report_date", columns)
        self.assertIsNone(self.conn.execute("SELECT report_date FROM downloaded_files").fetchone()["report_date"])


class ReportMembershipTest(TempDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        # legacy row: NULL report_date, uploaded 17.9
        self.legacy = self.add_article(self.add_file(1, "Guardian", "2026-09-17T10:00:00+00:00", None), "Guardian")
        # Economist-like row: uploaded late on 17.9 (UTC), downloaded - and therefore reported - on 18.9
        self.weekly = self.add_article(self.add_file(2, "Economist", "2026-09-17T23:09:38+00:00", "2026-09-18"), "Economist")
        # ordinary legacy row of 18.9
        self.same_day = self.add_article(self.add_file(3, "Daily Telegraph", "2026-09-18T04:00:00+00:00", None), "Daily Telegraph")
        # backlog row: uploaded 6.9, downloaded on 13.9
        self.backlog = self.add_article(self.add_file(4, "Washington Post", "2026-09-06T04:00:00+00:00", "2026-09-13"), "Washington Post")

    def ids_for(self, report_date: str) -> set[int]:
        return {r["id"] for r in db.get_articles_for_date(self.conn, report_date)}

    def test_legacy_rows_are_selected_by_upload_day(self):
        self.assertIn(self.legacy, self.ids_for("2026-09-17"))

    def test_new_rows_are_selected_by_report_date_not_by_upload_day(self):
        self.assertNotIn(self.weekly, self.ids_for("2026-09-17"))  # same upload day as the legacy row, yet excluded
        self.assertEqual(self.ids_for("2026-09-18"), {self.weekly, self.same_day})

    def test_backlog_rows_land_on_their_report_date(self):
        self.assertEqual(self.ids_for("2026-09-13"), {self.backlog})
        self.assertEqual(self.ids_for("2026-09-06"), set())

    def test_every_article_belongs_to_exactly_one_report_date(self):
        by_date = [self.ids_for(d) for d in ("2026-09-06", "2026-09-13", "2026-09-17", "2026-09-18")]
        all_ids = set().union(*by_date)
        self.assertEqual(all_ids, {self.legacy, self.weekly, self.same_day, self.backlog})
        self.assertEqual(sum(len(s) for s in by_date), len(all_ids))  # no overlap between report dates

    def test_sources_follow_the_same_rule(self):
        self.assertEqual(db.get_sources_for_date(self.conn, "2026-09-18"), ["Daily Telegraph", "Economist"])
        self.assertEqual(db.get_sources_for_date(self.conn, "2026-09-17"), ["Guardian"])

    def test_geo_tag_backfill_date_filter_follows_the_same_rule(self):
        ids = {r["id"] for r in db.get_articles_without_geo_tags(self.conn, "2026-09-18")}
        self.assertEqual(ids, {self.weekly, self.same_day})
        self.assertEqual(len(db.get_articles_without_geo_tags(self.conn)), 4)  # no date filter: everything

    def test_legacy_only_database_behaves_exactly_like_the_old_upload_day_rule(self):
        for message_id, published in ((10, "2026-08-24T04:00:00+00:00"), (11, "2026-08-24T22:59:00+00:00"), (12, "2026-08-25T00:01:00+00:00")):
            self.add_article(self.add_file(message_id, "Guardian", published, None), "Guardian")
        for day in ("2026-08-24", "2026-08-25"):
            old_rule = [r[0] for r in self.conn.execute(
                "SELECT a.id FROM articles a JOIN downloaded_files df ON df.id = a.file_id "
                "WHERE df.report_date IS NULL AND date(df.published_at) = ? ORDER BY a.newspaper, a.id", (day,))]
            new_rule = [r["id"] for r in db.get_articles_for_date(self.conn, day)]
            self.assertEqual(new_rule, old_rule)


class NoDirectPublishedAtSelectionTest(unittest.TestCase):
    """Guard: queries that pick 'the articles of report day X' must use db.REPORT_DATE_SQL."""

    def test_report_date_sql_is_the_agreed_expression(self):
        self.assertEqual(db.REPORT_DATE_SQL, "COALESCE(df.report_date, date(df.published_at))")

    def test_no_other_query_selects_by_date_of_published_at(self):
        # Allowed exactly twice in db.py: inside REPORT_DATE_SQL, and the citation date shown next to
        # each article ("The Guardian, 19.9.2026, p. 31"), which is deliberately the upload day.
        self.assertEqual(
            (SRC_DIR / "common" / "db.py").read_text(encoding="utf-8").count("date(df.published_at)"),
            2,
            "a new query filters by date(df.published_at); use REPORT_DATE_SQL instead",
        )
        for path in SRC_DIR.rglob("*.py"):
            if path.name != "db.py":
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("date(df.published_at)", text, f"{path.name} filters by published_at directly")
                self.assertNotIn("date(published_at)", text, f"{path.name} filters by published_at directly")


if __name__ == "__main__":
    unittest.main()
