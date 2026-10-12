"""Which period the overnight biweekly run picks, and when it picks none.

Pure date logic plus one injected "does this period already exist" lookup -
no tracker.db, no API. Weekdays are asserted explicitly so a wrong anchor
can't make these pass by accident.
"""
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from src.common.biweekly import latest_closed_period, missing_published_days, period_closing_on  # noqa: E402
import biweekly_autorun  # noqa: E402

P3 = (date(2026, 9, 17), date(2026, 9, 30))
P4 = (date(2026, 10, 1), date(2026, 10, 14))
ALREADY_IN_DB = {"2026-09-02", "2026-09-16", "2026-09-30"}


def exists(end_dates):
    return lambda end: end in end_dates


class LatestClosedPeriodTest(unittest.TestCase):
    def test_closing_day_is_a_wednesday_and_the_run_night_is_thursday(self):
        self.assertEqual(P4[1].strftime("%A"), "Wednesday")
        self.assertEqual(date(2026, 10, 15).strftime("%A"), "Thursday")

    def test_after_midnight_the_period_that_just_closed_is_found(self):
        self.assertEqual(latest_closed_period(date(2026, 10, 15)), P4)

    def test_period_closing_on_would_miss_it_after_midnight(self):
        # The reason the overnight run cannot reuse the daily run's old check.
        self.assertIsNone(period_closing_on(date(2026, 10, 15)))

    def test_on_the_closing_day_itself_the_period_is_not_closed_yet(self):
        self.assertEqual(latest_closed_period(date(2026, 10, 14)), P3)

    def test_max_age_cuts_off_old_periods(self):
        self.assertEqual(latest_closed_period(date(2026, 10, 22), max_age_days=8), P4)
        self.assertIsNone(latest_closed_period(date(2026, 10, 23), max_age_days=8))

    def test_before_the_first_period_closes_there_is_none(self):
        self.assertIsNone(latest_closed_period(date(2026, 8, 25)))


class DuePeriodTest(unittest.TestCase):
    def test_the_thursday_after_closing_picks_the_new_period(self):
        self.assertEqual(biweekly_autorun.due_period(date(2026, 10, 15), exists(ALREADY_IN_DB)), P4)

    def test_running_twice_is_a_no_op(self):
        after_first_run = ALREADY_IN_DB | {"2026-10-14"}
        self.assertIsNone(biweekly_autorun.due_period(date(2026, 10, 15), exists(after_first_run)))

    def test_the_off_week_thursday_is_a_no_op(self):
        after_first_run = ALREADY_IN_DB | {"2026-10-14"}
        self.assertIsNone(biweekly_autorun.due_period(date(2026, 10, 22), exists(after_first_run)))

    def test_a_missed_night_is_caught_up_the_following_thursday(self):
        self.assertEqual(biweekly_autorun.due_period(date(2026, 10, 22), exists(ALREADY_IN_DB)), P4)

    def test_no_catch_up_beyond_the_window(self):
        self.assertIsNone(biweekly_autorun.due_period(date(2026, 10, 23), exists(ALREADY_IN_DB)))

    def test_the_hand_migrated_periods_are_never_selected(self):
        # Every Thursday from the first live close through year end: whatever
        # is picked, it is never one of the three rows migrated by hand.
        d = date(2026, 10, 15)
        while d.year == 2026:
            picked = biweekly_autorun.due_period(d, exists(ALREADY_IN_DB))
            if picked is not None:
                self.assertNotIn(picked[1].isoformat(), ALREADY_IN_DB)
            d = date.fromordinal(d.toordinal() + 7)

    def test_the_wednesday_before_closing_night_picks_nothing_new(self):
        # Wednesday 15:00-ish: P4 has not ended, P3 already exists.
        self.assertIsNone(biweekly_autorun.due_period(date(2026, 10, 14), exists(ALREADY_IN_DB)))


class MissingPublishedDaysTest(unittest.TestCase):
    """A period may only be synthesized when every one of its days has a
    published daily report - in `reports` AND rendered under docs/he/."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.docs = Path(self._tmp.name)
        (self.docs / "he").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def publish(self, *isos):
        for iso in isos:
            (self.docs / "he" / f"report_{iso}_he.html").write_text("x", encoding="utf-8")

    def all_days(self, start, end):
        return [date.fromordinal(o).isoformat() for o in range(start.toordinal(), end.toordinal() + 1)]

    def test_a_complete_period_has_nothing_missing(self):
        days = self.all_days(*P4)
        self.publish(*days)
        self.assertEqual(missing_published_days(*P4, set(days), self.docs), [])

    def test_the_2026_10_12_incident_names_both_missing_days(self):
        # Run by hand two days before the period closed: 12 of 14 days existed.
        days = self.all_days(*P4)[:12]
        self.publish(*days)
        self.assertEqual(missing_published_days(*P4, set(days), self.docs), ["2026-10-13", "2026-10-14"])

    def test_a_gap_in_the_middle_is_named_too(self):
        days = [d for d in self.all_days(*P4) if d != "2026-10-06"]
        self.publish(*days)
        self.assertEqual(missing_published_days(*P4, set(days), self.docs), ["2026-10-06"])

    def test_a_report_in_the_db_but_not_yet_published_counts_as_missing(self):
        days = self.all_days(*P4)
        self.publish(*days[:-1])
        self.assertEqual(missing_published_days(*P4, set(days), self.docs), ["2026-10-14"])

    def test_a_published_file_with_no_db_row_counts_as_missing(self):
        days = self.all_days(*P4)
        self.publish(*days)
        self.assertEqual(missing_published_days(*P4, set(days[1:]), self.docs), ["2026-10-01"])


if __name__ == "__main__":
    unittest.main()
