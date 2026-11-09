"""scripts/tag_ratio_check.py: mix- and day-kind-adjusted tags per article with a z-score (PROJECT_LOG 4.135)."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts import tag_ratio_check as t
from src.common import db


def make_metrics(spec):
    """spec: {day: {paper: (articles, tags, named)}} -> the structure load_day_metrics returns."""
    return {d: {n: {"A": a, "tags": g, "named": m} for n, (a, g, m) in papers.items()} for d, papers in spec.items()}


# Mondays-to-Fridays 2026-10-12.. (weekday) and Saturdays/Sundays 2026-10-17/18.. (weekend)
WEEKDAYS = ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19", "2026-10-20", "2026-10-21"]
WEEKENDS = ["2026-10-17", "2026-10-18", "2026-10-24", "2026-10-25"]


def reference_spec(jitter=0.0):
    """Paper X tags 4 per article, paper Y 1 per article; a small deterministic wobble so the spread is not zero."""
    spec = {}
    for i, d in enumerate(WEEKDAYS + WEEKENDS):
        w = 1 + jitter * ((-1) ** i) * (1 + i % 3) / 3
        spec[d] = {"X": (20, round(80 * w), round(50 * w)), "Y": (20, round(20 * w), round(10 * w))}
    return spec


class KindTest(unittest.TestCase):
    def test_weekday_and_weekend(self):
        self.assertEqual(t.day_kind("2026-11-09"), "weekday")  # Monday
        self.assertEqual(t.day_kind("2026-11-07"), "weekend")  # Saturday
        self.assertEqual(t.day_kind("2026-11-08"), "weekend")  # Sunday


class AdjustmentTest(unittest.TestCase):
    def test_a_day_heavy_in_a_low_tagging_paper_is_not_a_drop(self):
        spec = reference_spec(0.05)
        spec["2026-11-09"] = {"X": (10, 40, 25), "Y": (50, 50, 25)}  # same per-paper rates, mix tilted to Y
        m = make_metrics(spec)
        row = t.series(m, ["2026-11-09"], ref=sorted(set(spec) - {"2026-11-09"}))[0]
        self.assertLess(row["raw_tags_per_article"], 2.0)  # raw looks like a big drop (1.5 against 2.5)
        self.assertAlmostEqual(row["tags_ratio"], 1.0, places=2)  # but the mix explains all of it
        self.assertGreater(row["tags_z"], -0.5)

    def test_a_real_drop_has_a_large_negative_z(self):
        spec = reference_spec(0.05)
        spec["2026-11-09"] = {"X": (20, 56, 35), "Y": (20, 14, 7)}  # 30% fewer tags at the same mix
        m = make_metrics(spec)
        ref = sorted(set(spec) - {"2026-11-09"})
        row = t.series(m, ["2026-11-09"], ref=ref)[0]
        self.assertAlmostEqual(row["tags_ratio"], 0.7, places=2)
        self.assertLess(row["tags_z"], -2.0)
        alert, reasons = t.alert_decision([row])
        self.assertTrue(alert)
        self.assertIn("below", reasons[0])

    def test_weekend_is_compared_with_weekends_only(self):
        spec = reference_spec(0.05)
        for d in WEEKENDS:  # weekends tag half as much as weekdays in this fixture
            spec[d] = {"X": (20, 40, 25), "Y": (20, 10, 5)}
        spec["2026-11-08"] = {"X": (20, 40, 25), "Y": (20, 10, 5)}  # a Sunday at the weekend rate
        m = make_metrics(spec)
        row = t.series(m, ["2026-11-08"], ref=sorted(set(spec) - {"2026-11-08"}))[0]
        self.assertAlmostEqual(row["tags_ratio"], 1.0, places=2)

    def test_days_with_too_few_articles_are_skipped(self):
        spec = reference_spec(0.05)
        spec["2026-11-09"] = {"X": (3, 0, 0)}
        rows = t.series(make_metrics(spec), ["2026-11-09"], ref=sorted(set(spec) - {"2026-11-09"}))
        self.assertEqual(rows, [])

    def test_named_ratio_is_reported_separately(self):
        spec = reference_spec(0.05)
        spec["2026-11-09"] = {"X": (20, 80, 25), "Y": (20, 20, 5)}  # same tags, half the named
        m = make_metrics(spec)
        row = t.series(m, ["2026-11-09"], ref=sorted(set(spec) - {"2026-11-09"}))[0]
        self.assertAlmostEqual(row["tags_ratio"], 1.0, places=2)
        self.assertAlmostEqual(row["named_ratio"], 0.5, places=1)
        self.assertLess(row["named_z"], -2.0)


class AlertRuleTest(unittest.TestCase):
    @staticmethod
    def row(day, z):
        return {"day": day, "tags_z": z}

    def test_one_day_below_minus_two_alerts(self):
        self.assertTrue(t.alert_decision([self.row("2026-11-09", -2.01)])[0])
        self.assertFalse(t.alert_decision([self.row("2026-11-09", -1.99)])[0])

    def test_three_consecutive_days_below_minus_one_and_a_half_alert(self):
        rows = [self.row("2026-11-07", -1.6), self.row("2026-11-08", -1.7), self.row("2026-11-09", -1.55)]
        alert, reasons = t.alert_decision(rows)
        self.assertTrue(alert)
        self.assertIn("3 consecutive", reasons[0])

    def test_two_days_or_a_gap_do_not_make_a_streak(self):
        self.assertFalse(t.alert_decision([self.row("2026-11-08", -1.7), self.row("2026-11-09", -1.7)])[0])
        gap = [self.row("2026-11-06", -1.7), self.row("2026-11-08", -1.7), self.row("2026-11-09", -1.7)]
        self.assertFalse(t.alert_decision(gap)[0])

    def test_one_mild_day_in_the_streak_breaks_it(self):
        rows = [self.row("2026-11-07", -1.6), self.row("2026-11-08", -1.2), self.row("2026-11-09", -1.9)]
        self.assertFalse(t.alert_decision(rows)[0])

    def test_no_data_is_not_an_alert(self):
        self.assertFalse(t.alert_decision([])[0])
        self.assertFalse(t.alert_decision([{"day": "2026-11-09", "tags_z": None}])[0])


class LoadTest(unittest.TestCase):
    def test_load_counts_articles_tags_and_named_tags_per_paper_and_day(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "t.db"
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row  # init_db reads PRAGMA rows by name
            db.init_db(conn)
            conn.execute("INSERT INTO downloaded_files (channel, message_id, file_name, newspaper, published_at, downloaded_at, local_path, report_date) "
                         "VALUES ('t', 1, 'a.pdf', 'Guardian', '2026-11-09T08:00:00+00:00', '2026-11-09T12:00:00+00:00', '/x', '2026-11-09')")
            fid = conn.execute("SELECT id FROM downloaded_files").fetchone()[0]
            for i, (headline, codes) in enumerate([("France votes on a new budget", ["FR", "DE"]), ("A quiet page", [])], 1):
                conn.execute("INSERT INTO articles (file_id, page_number, newspaper, language, headline, author, region_topic, stance_summary, key_excerpt, analyzed_at) "
                             "VALUES (?, ?, 'Guardian', 'en', ?, 'a', 'r', 's', 'k', 'x')", (fid, i, headline))
                aid = conn.execute("SELECT MAX(id) FROM articles").fetchone()[0]
                for c in codes:
                    conn.execute("INSERT INTO article_countries (article_id, country_code) VALUES (?, ?)", (aid, c))
            conn.commit()
            m = t.load_day_metrics(conn, "2026-11-01", "2026-11-30")
            conn.close()
        self.assertEqual(m["2026-11-09"]["Guardian"], {"A": 2, "tags": 2, "named": 1})  # FR is named in the headline, DE is not


if __name__ == "__main__":
    unittest.main()
