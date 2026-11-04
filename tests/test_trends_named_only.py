"""Conservative trends display: named-only filtering, the full week grid, n_articles and the low-volume flag
(PROJECT_LOG 4.122). Temp DB, no tracker.db, no API."""
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.common import db, trends  # noqa: E402
from src.publishing import publish  # noqa: E402


class NamedOnlyTrendsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.get_connection(Path(self.tmp.name) / "t.db")
        db.init_db(self.conn)
        self.n = 0

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def add(self, rdate, newspaper, headline, summary, countries):
        self.n += 1
        db.mark_downloaded(self.conn, "t", self.n, f"f{self.n}.pdf", newspaper, f"{rdate}T10:00:00+00:00", f"{rdate}T10:00:00+00:00", "/x")
        self.conn.execute("UPDATE downloaded_files SET report_date = ? WHERE message_id = ?", (rdate, self.n))
        file_id = self.conn.execute("SELECT id FROM downloaded_files WHERE message_id = ?", (self.n,)).fetchone()["id"]
        article_id = db.insert_article(self.conn, file_id, 1, newspaper, "en", headline, "", "t", summary, "", "2026-11-02T00:00:00")
        db.insert_article_countries(self.conn, article_id, countries)
        return article_id

    def test_a_tag_without_the_name_is_dropped_and_the_default_keeps_it(self):
        self.add("2026-10-01", "Guardian", "Markets wobble", "Analysts debate rates", ["FR"])
        self.add("2026-10-01", "Die Welt", "Frankreich wählt", "Wahl in Paris", ["FR"])
        kept = trends.get_country_article_rows(self.conn, named_only=True)
        self.assertEqual([(cc, np) for cc, _, np, _ in kept], [("FR", "Die Welt")])
        self.assertEqual(len(trends.get_country_article_rows(self.conn)), 2)
        self.assertEqual(len(trends.get_country_date_source_rows(self.conn)), 2)

    def test_the_filter_never_adds_a_country_the_model_did_not_tag(self):
        self.add("2026-10-01", "Guardian", "Russia and Iran", "Kremlin and Tehran talk", ["RU"])
        got = {cc for cc, *_ in trends.get_country_article_rows(self.conn, named_only=True)}
        self.assertEqual(got, {"RU"})

    def test_the_week_grid_comes_from_all_dates_not_the_filtered_ones(self):
        self.add("2026-10-01", "Guardian", "Markets", "rates", ["FR"])  # unnamed: dropped by the filter
        self.add("2026-10-09", "Die Welt", "Frankreich", "Paris", ["FR"])
        series = trends.build_country_week_trends(self.conn, named_only=True)["FR"]
        self.assertEqual([w["week_start"] for w in series], ["2026-10-01", "2026-10-08"])
        self.assertEqual([w["n_sources"] for w in series], [0, 1])
        self.assertEqual([w["n_articles"] for w in series], [0, 1])

    def test_every_key_has_one_entry_per_week(self):
        self.add("2026-10-01", "Guardian", "Frankreich", "Paris", ["FR"])
        self.add("2026-10-09", "Guardian", "Germany", "Berlin", ["DE"])
        out = trends.build_country_week_trends(self.conn, named_only=True)
        self.assertEqual({k: len(v) for k, v in out.items()}, {"FR": 2, "DE": 2})
        self.assertEqual([w["n_sources"] for w in out["FR"]], [1, 0])

    def test_trends_json_marks_lower_bound_and_low_volume_weeks(self):
        self.add("2026-10-01", "Guardian", "France votes", "Paris decides", ["FR"])
        for i in range(10):
            self.add("2026-10-08", "Guardian" if i % 2 else "Die Welt", f"France story {i}", "Paris", ["FR"])
        data = publish.build_trends_json(self.conn)
        self.assertEqual(data["counting"], {"method": "named_only", "lower_bound": True, "min_articles_per_point": 10})
        self.assertEqual(len(data["weeks"]), 2)
        fr = next(c for c in data["countries"] if c["code"] == "FR")
        self.assertEqual(fr["n_articles"], [1, 10])
        self.assertEqual(fr["low_volume"], [True, False])
        self.assertEqual(fr["n_sources"], [1, 2])

    def test_weeks_do_not_depend_on_which_eligible_country_comes_first(self):
        self.add("2026-10-01", "Guardian", "France", "Paris", ["FR"])
        self.add("2026-10-01", "Guardian", "Germany", "Berlin", ["DE"])
        self.add("2026-10-09", "Guardian", "France", "Paris", ["FR"])
        self.add("2026-10-09", "Guardian", "Germany", "Berlin", ["DE"])
        for _ in range(5):
            self.assertEqual([w["start"] for w in publish.build_trends_json(self.conn)["weeks"]], ["2026-10-01", "2026-10-08"])


if __name__ == "__main__":
    unittest.main()
