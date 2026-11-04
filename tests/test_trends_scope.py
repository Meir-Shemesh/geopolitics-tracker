"""SCOPE_BREAKS and weekly_roster (PROJECT_LOG 4.116)."""

import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import db, trends
from src.publishing import publish


class ScopeBreaksTest(unittest.TestCase):
    def test_every_break_is_well_formed(self):
        for b in trends.SCOPE_BREAKS:
            date.fromisoformat(b["date"])
            self.assertIn(b["axis"], ("analysis_scope", "source_roster"))
            for lang in ("he", "en", "de"):
                self.assertTrue(b[f"label_{lang}"].strip(), (b["date"], lang))

    def test_breaks_are_in_date_order_and_cover_both_axes(self):
        dates = [b["date"] for b in trends.SCOPE_BREAKS]
        self.assertEqual(dates, sorted(dates))
        self.assertEqual({b["axis"] for b in trends.SCOPE_BREAKS}, {"analysis_scope", "source_roster"})
        self.assertIn("2026-10-02", [b["date"] for b in trends.SCOPE_BREAKS if b["axis"] == "analysis_scope"])

    def test_json_copy_is_independent_of_the_constant(self):
        out = trends.scope_breaks_for_json()
        out[0]["date"] = "1999-01-01"
        self.assertNotEqual(trends.SCOPE_BREAKS[0]["date"], "1999-01-01")


class WeeklyRosterTest(unittest.TestCase):
    def test_union_over_the_week_sorted_and_empty_week_is_empty(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE reports (report_date TEXT PRIMARY KEY, sources_included TEXT NOT NULL)")
        rows = [("2026-10-01", ["Guardian", "Die Welt"]), ("2026-10-03", ["Economist", "Guardian"]), ("2026-10-09", ["Der Spiegel"])]
        conn.executemany("INSERT INTO reports VALUES (?, ?)", [(d, json.dumps(s)) for d, s in rows])
        weeks = [{"start": "2026-10-01", "end": "2026-10-07"}, {"start": "2026-10-08", "end": "2026-10-14"}, {"start": "2026-10-15", "end": "2026-10-21"}]
        self.assertEqual(trends.weekly_roster(conn, weeks), [["Die Welt", "Economist", "Guardian"], ["Der Spiegel"], []])


class CountryOrderTieBreakTest(unittest.TestCase):
    def test_equal_totals_are_ordered_by_code_every_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.get_connection(Path(tmp) / "t.db")
            db.init_db(conn)
            names = {"PL": "Poland", "FR": "France", "DE": "Germany", "IT": "Italy"}  # named, so it also holds under the named-only display
            for i, code in enumerate(["PL", "FR", "DE", "IT"], start=1):
                db.mark_downloaded(conn, "t", i, f"f{i}.pdf", "Guardian", "2026-10-01T10:00:00+00:00", "2026-10-01T10:00:00+00:00", "/x")
                conn.execute("UPDATE downloaded_files SET report_date = '2026-10-01' WHERE message_id = ?", (i,))
                file_id = conn.execute("SELECT id FROM downloaded_files WHERE message_id = ?", (i,)).fetchone()["id"]
                aid = db.insert_article(conn, file_id, 1, "Guardian", "en", names[code], "", "t", "s", "", "2026-11-02T00:00:00")
                db.insert_article_countries(conn, aid, [code])
            orders = {tuple(c["code"] for c in publish.build_trends_json(conn)["countries"]) for _ in range(5)}
            conn.close()
        self.assertEqual(orders, {("DE", "FR", "IT", "PL")})


if __name__ == "__main__":
    unittest.main()
