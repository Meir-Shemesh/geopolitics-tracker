"""The end-of-stage API usage summary (db.summarize_api_usage / print_usage_summary): totals, cache hit rate, the
estimated cost, the stage and time filters, and that it never fails a stage. Temp DBs only - no network, no tracker.db."""
import io
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.common import db  # noqa: E402

SONNET, HAIKU = "claude-sonnet-5", "claude-haiku-4-5-20251001"


def usage(tokens_in, tokens_out, cache_write=0, cache_read=0):
    return SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out,
                           cache_creation_input_tokens=cache_write, cache_read_input_tokens=cache_read)


class UsageSummaryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "t.db"
        conn = db.get_connection(self.path)
        db.init_db(conn)
        conn.close()
        os.environ.pop("TRACKER_NO_USAGE_LOG", None)
        self.addCleanup(self.tmp.cleanup)

    def record(self, stage, model, u):
        db.record_api_usage(stage, model, u, db_path=self.path)

    def test_totals_cache_hit_rate_and_cost(self):
        since = db.usage_marker()
        self.record("analyze", SONNET, usage(1000, 100, cache_read=4000))
        self.record("analyze", SONNET, usage(1000, 100, cache_write=4000))
        total = db.summarize_api_usage(since, "analyze", self.path)
        self.assertEqual((total["calls"], total["input"], total["output"], total["cache_write"], total["cache_read"]),
                         (2, 2000, 200, 4000, 4000))
        self.assertAlmostEqual(total["cache_hit_rate"], 4000 / 10000)
        # (2000 in * $2 + 4000 write * $2 * 1.25 + 4000 read * $2 * 0.1 + 200 out * $10) per million
        self.assertAlmostEqual(total["cost"], (2000 * 2 + 4000 * 2.5 + 4000 * 0.2 + 200 * 10) / 1e6)

    def test_only_the_stage_and_the_time_window_are_counted(self):
        self.record("screen", HAIKU, usage(500, 10))                 # before the marker
        time.sleep(1.1)                                              # called_at has one-second resolution
        since = db.usage_marker()
        self.record("screen", HAIKU, usage(700, 20))
        self.record("analyze", SONNET, usage(900, 30))
        self.assertEqual(db.summarize_api_usage(since, "screen", self.path)["input"], 700)
        self.assertEqual(db.summarize_api_usage(since, "", self.path)["calls"], 2)
        self.assertEqual(db.summarize_api_usage(since, "synthesize_stage", self.path)["calls"], 0)

    def test_an_unknown_model_is_counted_but_never_priced(self):
        since = db.usage_marker()
        self.record("analyze", "some-future-model", usage(1000, 100))
        total = db.summarize_api_usage(since, "analyze", self.path)
        self.assertEqual((total["calls"], total["cost"], total["unpriced"]), (1, 0.0, 1))
        self.assertIn("unknown price", db.format_usage_summary("analyze", total))

    def test_the_summary_line_and_the_empty_case(self):
        since = db.usage_marker()
        self.assertEqual(db.format_usage_summary("screen", db.summarize_api_usage(since, "screen", self.path)),
                         "API usage (screen): no calls")
        self.record("screen", HAIKU, usage(2000, 50))
        line = db.format_usage_summary("screen", db.summarize_api_usage(since, "screen", self.path))
        for part in ("1 calls", "input 2,000", "output 50", "cache write 0", "cache read 0", "cache hit 0%", "est. $0.0"):
            self.assertIn(part, line)

    def test_prices_match_the_cost_report_script(self):
        from scripts import usage_report
        self.assertEqual(db.API_PRICES_PER_MTOK, usage_report.PRICES)

    def test_a_failure_never_reaches_the_stage(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            original = db.DB_PATH
            db.DB_PATH = Path(self.tmp.name) / "missing" / "nope.db"
            try:
                db.print_usage_summary("screen", db.usage_marker(), "screen")
            finally:
                db.DB_PATH = original
        self.assertEqual(out.getvalue(), "")
        self.assertIn("usage summary skipped", err.getvalue())


if __name__ == "__main__":
    unittest.main()
