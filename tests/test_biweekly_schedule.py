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

from unittest import mock  # noqa: E402

from src.common import biweekly  # noqa: E402
from src.common.biweekly import (  # noqa: E402
    expected_rolling_window,
    latest_closed_period,
    latest_weekly_run_day,
    missing_published_days,
    period_closing_on,
    rolling_window,
)
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


class CircuitBreakerTest(unittest.TestCase):
    """biweekly_autorun.apply_outcome: what each outcome does to the
    consecutive-failure count, and when the breaker trips."""

    NOW = "2026-10-15T01:30:05"

    def run_sequence(self, *outcomes):
        state, tripped = dict(biweekly_autorun.DEFAULT_STATE), False
        for outcome in outcomes:
            state, tripped = biweekly_autorun.apply_outcome(state, outcome, "detail", "p", self.NOW)
        return state, tripped

    def test_one_failure_does_not_trip(self):
        state, tripped = self.run_sequence("failed")
        self.assertEqual(state["consecutive_failures"], 1)
        self.assertFalse(tripped)

    def test_the_second_consecutive_failure_trips(self):
        state, tripped = self.run_sequence("failed", "failed")
        self.assertEqual(state["consecutive_failures"], biweekly_autorun.CONSECUTIVE_FAILURE_LIMIT)
        self.assertTrue(tripped)

    def test_a_published_report_resets_the_count(self):
        state, tripped = self.run_sequence("failed", "published", "failed")
        self.assertEqual(state["consecutive_failures"], 1)
        self.assertFalse(tripped)

    def test_an_expected_skip_resets_the_count_and_is_not_a_success_or_a_failure(self):
        state, tripped = self.run_sequence("failed", "skipped")
        self.assertEqual((state["consecutive_failures"], state["last_outcome"], tripped), (0, "skipped", False))

    def test_a_manual_pause_neither_counts_nor_resets(self):
        state, tripped = self.run_sequence("failed", "paused")
        self.assertEqual((state["consecutive_failures"], state["last_outcome"], tripped), (1, "paused", False))

    def test_running_into_the_kill_switch_does_not_trip_it_again(self):
        state, tripped = self.run_sequence("failed", "failed", "stopped")
        self.assertEqual((state["consecutive_failures"], tripped), (2, False))

    def test_state_files_are_not_the_daily_ones(self):
        import daily_autorun
        daily = {daily_autorun.STATE_FILE, daily_autorun.CONFIG_FILE, daily_autorun.KILLSWITCH_FLAG, daily_autorun.PAUSE_FLAG}
        biweekly = {biweekly_autorun.STATE_FILE, biweekly_autorun.KILLSWITCH_FLAG, biweekly_autorun.PAUSE_NEXT_FLAG}
        self.assertFalse(daily & biweekly)


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


class RollingWindowTest(unittest.TestCase):
    """The rolling mode (PROJECT_LOG 4.106): 14 days ending YESTERDAY, from the run date alone."""

    def test_window_is_the_14_days_ending_the_day_before_the_run(self):
        start, end = rolling_window(date(2026, 10, 22))  # a Thursday
        self.assertEqual((start, end), (date(2026, 10, 8), date(2026, 10, 21)))
        self.assertEqual((end - start).days + 1, 14)
        self.assertEqual(end.strftime("%A"), "Wednesday")

    def test_window_never_depends_on_the_fixed_periods(self):
        # Not 2026-10-28 (what the fixed cadence would close next): an ordinary Thursday gives its own window,
        # overlapping the last archived fixed period (10-01..10-14) on purpose.
        self.assertEqual(rolling_window(date(2026, 10, 22)), (date(2026, 10, 8), date(2026, 10, 21)))
        self.assertEqual(rolling_window(date(2026, 10, 29)), (date(2026, 10, 15), date(2026, 10, 28)))
        self.assertEqual(rolling_window(date(2026, 11, 5)), (date(2026, 10, 22), date(2026, 11, 4)))

    def test_year_boundary(self):
        self.assertEqual(rolling_window(date(2027, 1, 7)), (date(2026, 12, 24), date(2027, 1, 6)))

    def test_latest_weekly_run_day_and_expected_window(self):
        self.assertEqual(latest_weekly_run_day(date(2026, 10, 22)), date(2026, 10, 22))  # Thursday itself
        self.assertEqual(latest_weekly_run_day(date(2026, 10, 25)), date(2026, 10, 22))  # Sunday after
        self.assertEqual(latest_weekly_run_day(date(2026, 10, 21)), date(2026, 10, 15))  # Wednesday before
        self.assertEqual(expected_rolling_window(date(2026, 10, 24)), (date(2026, 10, 8), date(2026, 10, 21)))

    def test_due_unless_a_report_with_that_end_date_exists(self):
        window = (date(2026, 10, 8), date(2026, 10, 21))
        self.assertEqual(biweekly_autorun.due_rolling_window(date(2026, 10, 22), exists(ALREADY_IN_DB)), window)
        self.assertIsNone(biweekly_autorun.due_rolling_window(date(2026, 10, 22), exists({"2026-10-21"})))

    def test_every_thursday_is_due_unlike_the_fixed_mode(self):
        done = set(ALREADY_IN_DB)
        for run_day in (date(2026, 10, 22), date(2026, 10, 29), date(2026, 11, 5), date(2026, 11, 12)):
            window = biweekly_autorun.due_rolling_window(run_day, exists(done))
            self.assertIsNotNone(window, run_day)
            done.add(window[1].isoformat())  # that Thursday's report is written
            self.assertIsNone(biweekly_autorun.due_rolling_window(run_day, exists(done)))

    def test_the_switch_chooses_the_mode(self):
        in_db = exists(ALREADY_IN_DB | {"2026-10-14"})
        with mock.patch.object(biweekly, "ROLLING_WINDOW_ENABLED", False):
            self.assertIsNone(biweekly_autorun.select_due(date(2026, 10, 22), in_db))  # fixed: nothing due on this Thursday
        with mock.patch.object(biweekly, "ROLLING_WINDOW_ENABLED", True):
            self.assertEqual(biweekly_autorun.select_due(date(2026, 10, 22), in_db), (date(2026, 10, 8), date(2026, 10, 21)))

    def test_the_hub_and_homepage_pick_the_latest_by_end_date_not_by_insertion_order(self):
        # get_all_biweekly_periods orders by end_date DESC and _biweekly_latest_entry takes the first row;
        # a rolling report inserted later but ending earlier than an existing one must not win.
        import sqlite3
        from src.common import db
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        db.init_db(conn)
        for start, end in (("2026-10-08", "2026-10-21"), ("2026-10-01", "2026-10-14"), ("2026-10-15", "2026-10-28")):
            db.insert_biweekly_period(conn, start, end, "o", "o", "o", "2026-10-30T00:00:00+00:00")
        self.assertEqual([r["end_date"] for r in db.get_all_biweekly_periods(conn)],
                         ["2026-10-28", "2026-10-21", "2026-10-14"])


class StartEmailTest(unittest.TestCase):
    PERIOD = (date(2026, 10, 8), date(2026, 10, 21))

    def test_the_start_email_names_the_window_and_the_mode(self):
        sent = []
        with mock.patch.object(biweekly_autorun.autorun, "send_email", lambda subj, body: sent.append((subj, body))):
            with mock.patch.object(biweekly, "ROLLING_WINDOW_ENABLED", True):
                self.assertTrue(biweekly_autorun.notify_started(self.PERIOD, Path("x.log"), lambda m: None))
        subject, body = sent[0]
        self.assertIn("2026-10-08..2026-10-21", subject)
        self.assertIn("run started", subject)
        self.assertIn("2026-10-08 .. 2026-10-21 (14 days)", body)
        self.assertIn("rolling 14-day window", body)

    def test_a_mail_failure_never_stops_the_run_or_touches_state(self):
        logged = []

        def boom(subject, body):
            raise OSError("smtp down")

        with mock.patch.object(biweekly_autorun.autorun, "send_email", boom),                 mock.patch.object(biweekly_autorun.autorun, "save_json") as save:
            self.assertFalse(biweekly_autorun.notify_started(self.PERIOD, Path("x.log"), logged.append))
        save.assert_not_called()
        self.assertTrue(any("Could not send start email" in m for m in logged))


if __name__ == "__main__":
    unittest.main()
