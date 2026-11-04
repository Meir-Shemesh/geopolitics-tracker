"""CORE_V1 (nine papers, Washington Post included) and the cadence-based definition of an active paper
(PROJECT_LOG 4.116)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import trends  # noqa: E402
from src.reporting.render import NEWSPAPER_COUNTRIES  # noqa: E402


class CoreV1Test(unittest.TestCase):
    def test_the_list_is_the_decided_nine(self):
        self.assertEqual(
            sorted(trends.CORE_V1),
            sorted(["Daily Telegraph", "Der Spiegel", "Die Welt", "Economist", "Guardian", "Los Angeles Times",
                    "Süddeutsche Zeitung", "USA Today", "Washington Post"]),
        )

    def test_it_is_immutable_and_excludes_the_decided_out_papers(self):
        self.assertIsInstance(trends.CORE_V1, tuple)
        for out in ("Wall Street Journal", "Observer", "Frankfurter Allgemeine Zeitung", "Neue Zürcher Zeitung", "Globe and Mail"):
            self.assertNotIn(out, trends.CORE_V1)

    def test_every_member_is_a_known_newspaper_key(self):
        for paper in trends.CORE_V1:
            self.assertIn(paper, NEWSPAPER_COUNTRIES, paper)


class CadenceTest(unittest.TestCase):
    def test_cadence_from_the_measured_delivery_rates(self):
        # rates measured on the issue-date axis, 2.11.2026
        for paper, rate, expected in (("Economist", 0.16, "weekly"), ("Der Spiegel", 0.17, "weekly"), ("Observer", 0.25, "weekly"),
                                      ("Die Welt", 0.65, "daily"), ("Wall Street Journal", 0.62, "daily"), ("Guardian", 0.75, "daily"),
                                      ("Washington Post", 0.95, "daily")):
            self.assertEqual(trends.paper_cadence(rate), expected, paper)

    def test_weekly_paper_needs_one_issue(self):
        self.assertTrue(trends.is_paper_active("weekly", 1, 1.0))
        self.assertFalse(trends.is_paper_active("weekly", 0, 1.0))

    def test_daily_paper_needs_half_of_its_expected_issues_and_at_least_one(self):
        self.assertTrue(trends.is_paper_active("daily", 3, 6.0))
        self.assertFalse(trends.is_paper_active("daily", 2, 6.0))
        self.assertTrue(trends.is_paper_active("daily", 1, 1.4))  # a short span: one issue is enough
        self.assertFalse(trends.is_paper_active("daily", 0, 1.4))

    def test_outside_the_papers_own_span_is_never_active(self):
        self.assertFalse(trends.is_paper_active("daily", 0, 0.0))
        self.assertFalse(trends.is_paper_active("weekly", 5, 0.0))


if __name__ == "__main__":
    unittest.main()
