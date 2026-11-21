"""The fetch ceiling override of scripts/daily_autorun.py (2026-11-21): GEO_FETCH_TIMEOUT_SECONDS, then fetch_timeout_seconds in
config.json, then 7,200 s; an invalid value is ignored with a log line, a valid one outside 600-28,800 s is clamped with a log line.

Pure: resolve_fetch_timeout takes the two raw values, so there is no environment, no config file, no API and no tracker.db."""
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import daily_autorun as da  # noqa: E402

ENV = "env GEO_FETCH_TIMEOUT_SECONDS"
CONFIG = "config.json fetch_timeout_seconds"


class DefaultAndSourcesTest(unittest.TestCase):
    def test_nothing_set_keeps_7200_seconds(self):
        self.assertEqual(da.resolve_fetch_timeout(None, None), (7200, "default", []))
        self.assertEqual(da.FETCH_TIMEOUT_DEFAULT_SECONDS, 7200)

    def test_a_valid_environment_value_is_used(self):
        self.assertEqual(da.resolve_fetch_timeout("18000", None), (18000, ENV, []))

    def test_a_valid_config_value_is_used(self):
        self.assertEqual(da.resolve_fetch_timeout(None, 10800), (10800, CONFIG, []))

    def test_the_environment_beats_the_config(self):
        self.assertEqual(da.resolve_fetch_timeout("18000", 10800), (18000, ENV, []))

    def test_a_numeric_string_with_spaces_or_a_decimal_is_accepted(self):
        self.assertEqual(da.resolve_fetch_timeout(" 18000 ", None)[:2], (18000, ENV))
        self.assertEqual(da.resolve_fetch_timeout("18000.0", None)[:2], (18000, ENV))
        self.assertEqual(da.resolve_fetch_timeout(None, "9000")[:2], (9000, CONFIG))


class InvalidValuesTest(unittest.TestCase):
    def test_invalid_values_are_ignored_with_a_log_line(self):
        for bad in ("abc", "", "   ", "-5", "-18000", "0", "nan", "inf", "12h"):
            with self.subTest(env=bad):
                seconds, source, notes = da.resolve_fetch_timeout(bad, None)
                self.assertEqual((seconds, source), (7200, "default"))
                self.assertEqual(len(notes), 1)
                self.assertIn("ignoring", notes[0])
                self.assertIn(ENV, notes[0])

    def test_a_bool_or_a_list_in_the_config_is_not_a_number(self):
        for bad in (True, [18000], {"a": 1}):
            with self.subTest(config=bad):
                seconds, source, notes = da.resolve_fetch_timeout(None, bad)
                self.assertEqual((seconds, source), (7200, "default"))
                self.assertIn("ignoring", notes[0])

    def test_an_invalid_environment_falls_back_to_a_valid_config(self):
        seconds, source, notes = da.resolve_fetch_timeout("abc", 10800)
        self.assertEqual((seconds, source), (10800, CONFIG))
        self.assertEqual(len(notes), 1)

    def test_both_invalid_gives_the_default_and_two_lines(self):
        seconds, source, notes = da.resolve_fetch_timeout("abc", -1)
        self.assertEqual((seconds, source, len(notes)), (7200, "default", 2))


class LimitsTest(unittest.TestCase):
    def test_below_the_minimum_is_raised_to_600_with_a_log_line(self):
        seconds, source, notes = da.resolve_fetch_timeout("30", None)
        self.assertEqual((seconds, source), (600, ENV))
        self.assertIn("clamped to 600s", notes[0])

    def test_above_the_maximum_is_cut_to_28800_with_a_log_line(self):
        seconds, source, notes = da.resolve_fetch_timeout("999999", None)
        self.assertEqual((seconds, source), (28800, ENV))
        self.assertIn("clamped to 28800s", notes[0])
        seconds, source, notes = da.resolve_fetch_timeout(None, 100000)
        self.assertEqual((seconds, source), (28800, CONFIG))

    def test_the_limits_themselves_are_not_clamped(self):
        self.assertEqual(da.resolve_fetch_timeout("600", None), (600, ENV, []))
        self.assertEqual(da.resolve_fetch_timeout("28800", None), (28800, ENV, []))

    def test_resolving_never_changes_the_ceiling_table(self):
        before = dict(da.TIMEOUTS)
        da.resolve_fetch_timeout("18000", 10800)
        self.assertEqual(da.TIMEOUTS, before)


if __name__ == "__main__":
    unittest.main()
