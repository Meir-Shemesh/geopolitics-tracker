"""screen.py's API-time vs code-time measurement and daily_autorun's non-fatal failure email (PROJECT_LOG 4.113).

No API, no real database, no network: screen_page() and smtplib are mocked, the clock is patched where a number matters.
"""

import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import daily_autorun
from src.analysis import screen
from src.common import db

LONG = "The prime minister said on Thursday that the sanctions on the northern ports would stay in place. " * 4
OTHER = "Opposition leaders demanded an inquiry into how the defence contract was awarded last spring. " * 4


class ScreenTimingsTest(unittest.TestCase):
    def test_summary_splits_api_and_code(self):
        t = screen.ScreenTimings()
        for api, code in [(2.0, 0.01), (4.0, 0.03), (0.0, 0.02)]:  # the last page never called the API
            t.add(api, code)
        text = t.summary(1.5)
        self.assertIn("setup 1.5s", text)
        self.assertIn("API: 2 x, total 6.00s, mean 3.00s", text)
        self.assertIn("max 4.00s", text)
        self.assertIn("code per page: 3 x, total 0.060s, mean 0.020s", text)
        self.assertIn("p95", text.split("code per page")[1])

    def test_summary_with_no_api_calls_and_with_no_pages(self):
        t = screen.ScreenTimings()
        self.assertIn("no page processed", t.summary(0.2))
        t.add(0.0, 0.01)
        self.assertIn("no API calls", t.summary(0.2))


class ScreenRunTimingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"
        self.conn = self.connect()
        db.init_db(self.conn)

        def slow_screen_page(client, raw_text, model=None, ref=None):
            self.fake_clock[0] += 3.0  # a 3-second API call
            return True, "fake verdict"

        self.fake_clock = [1000.0]
        patches = [
            mock.patch.object(screen, "get_connection", side_effect=self.connect),
            mock.patch.object(screen, "screen_page", side_effect=slow_screen_page),
            mock.patch.object(screen.anthropic, "Anthropic", return_value=mock.Mock()),
            mock.patch.object(screen, "load_dotenv"),
            mock.patch.object(screen.time, "perf_counter", side_effect=lambda: self.fake_clock[0]),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def add_file(self, message_id: int, texts: list[str]) -> int:
        cursor = self.conn.execute(
            "INSERT INTO downloaded_files (channel, message_id, file_name, newspaper, published_at, downloaded_at, "
            "local_path, report_date) VALUES ('t', ?, ?, 'Guardian', '2026-10-31T10:00:00+00:00', "
            "'2026-10-31T12:00:00+00:00', '/missing.pdf', '2026-10-31')", (message_id, f"f{message_id}.pdf"))
        for n, text in enumerate(texts, start=1):
            self.conn.execute("INSERT INTO extracted_pages (file_id, page_number, raw_text, extracted_at) "
                              "VALUES (?, ?, ?, 'x')", (cursor.lastrowid, n, text))
        self.conn.commit()
        return cursor.lastrowid

    def run_screen(self) -> list[str]:
        with mock.patch("builtins.print") as printed:
            screen.run()
        return [str(c.args[0]) for c in printed.call_args_list if c.args]

    def test_each_page_line_and_the_summary_carry_the_split(self):
        self.add_file(1, [LONG, OTHER, LONG])  # page 3 repeats page 1: a text duplicate, no API call
        lines = self.run_screen()
        page_lines = [l for l in lines if re.match(r"\s+page \d+ \(file", l)]
        self.assertEqual(len(page_lines), 3)
        self.assertEqual(sum("[api 3.00s, code 0.000s]" in l for l in page_lines), 2)
        self.assertEqual(sum("[api 0.00s, code 0.000s]" in l and "DUPLICATE" in l for l in page_lines), 1)
        summary = next(l for l in lines if l.startswith("Timing:"))
        self.assertIn("API: 2 x, total 6.00s, mean 3.00s", summary)
        self.assertIn("code per page: 3 x", summary)

    def test_a_failed_call_still_reports_how_long_it_took(self):
        self.add_file(1, [LONG])

        def failing(client, raw_text, model=None, ref=None):
            self.fake_clock[0] += 60.0
            raise RuntimeError("timeout")

        with mock.patch.object(screen, "screen_page", side_effect=failing):
            lines = self.run_screen()
        self.assertTrue(any("failed:" in l and "after 60.00s" in l for l in lines))
        self.assertTrue(any(l.startswith("Timing:") for l in lines))


class SafeEmailTest(unittest.TestCase):
    def test_a_failing_send_is_logged_and_swallowed(self):
        logged = []
        with mock.patch.object(daily_autorun, "send_email", side_effect=OSError("network unreachable")):
            ok = daily_autorun.send_email_safely(logged.append, "[Geopolitics Tracker] Daily run FAILED", "body")
        self.assertFalse(ok)
        self.assertEqual(len(logged), 1)
        self.assertIn("EMAIL SEND FAILED", logged[0])
        self.assertIn("network unreachable", logged[0])

    def test_a_good_send_logs_nothing(self):
        logged = []
        with mock.patch.object(daily_autorun, "send_email") as sent:
            ok = daily_autorun.send_email_safely(logged.append, "subject", "body")
        self.assertTrue(ok)
        sent.assert_called_once_with("subject", "body")
        self.assertEqual(logged, [])

    def test_main_never_calls_the_raw_send_email(self):
        import inspect
        body = inspect.getsource(daily_autorun.main)
        self.assertNotRegex(body, r"(?<!_)send_email\(")


if __name__ == "__main__":
    unittest.main()
