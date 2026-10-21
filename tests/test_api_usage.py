"""Token-usage logging (PROJECT_LOG 4.107) and the prompt-cache breakpoint in analyze_page.
Temp DBs and fake API clients only - no network, no tracker.db."""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.analysis import analyze, screen  # noqa: E402
from src.common import db  # noqa: E402
from scripts import usage_report  # noqa: E402


def make_db(directory: str) -> Path:
    path = Path(directory) / "t.db"
    conn = db.get_connection(path)
    db.init_db(conn)
    conn.close()
    return path


def rows(path: Path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT stage, model, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens, ref FROM api_usage").fetchall()
    finally:
        conn.close()


class RecordApiUsageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = make_db(self.tmp.name)
        os.environ.pop("TRACKER_NO_USAGE_LOG", None)

    def tearDown(self):
        os.environ.pop("TRACKER_NO_USAGE_LOG", None)
        self.tmp.cleanup()

    def test_a_real_usage_object_is_recorded_with_cache_counts(self):
        usage = SimpleNamespace(input_tokens=100, output_tokens=20, cache_creation_input_tokens=4000, cache_read_input_tokens=0)
        db.record_api_usage("analyze", "claude-sonnet-5", usage, ref="5:3", db_path=self.path)
        self.assertEqual(rows(self.path), [("analyze", "claude-sonnet-5", 100, 20, 4000, 0, "5:3")])

    def test_missing_cache_fields_default_to_zero(self):
        db.record_api_usage("screen", "m", SimpleNamespace(input_tokens=5, output_tokens=1), db_path=self.path)
        self.assertEqual(rows(self.path)[0][4:6], (0, 0))

    def test_a_mocked_response_and_the_opt_out_record_nothing(self):
        db.record_api_usage("screen", "m", mock.MagicMock(), db_path=self.path)
        os.environ["TRACKER_NO_USAGE_LOG"] = "1"
        db.record_api_usage("screen", "m", SimpleNamespace(input_tokens=5, output_tokens=1), db_path=self.path)
        self.assertEqual(rows(self.path), [])

    def test_logging_never_raises_even_with_no_table(self):
        empty = Path(self.tmp.name) / "empty.db"
        sqlite3.connect(empty).close()
        db.record_api_usage("screen", "m", SimpleNamespace(input_tokens=5, output_tokens=1), db_path=empty)  # must not raise


class StageHooksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = make_db(self.tmp.name)
        os.environ.pop("TRACKER_NO_USAGE_LOG", None)
        self.patch = mock.patch.object(db, "DB_PATH", self.path)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    @staticmethod
    def fake_client(tool_input, usage):
        response = SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=tool_input)], usage=usage)
        create = mock.Mock(return_value=response)
        client = mock.Mock()
        client.messages.create = create
        client.with_options.return_value = client
        return client, create

    def test_screen_page_records_its_call(self):
        client, _ = self.fake_client({"is_relevant": True, "reasoning": "x"}, SimpleNamespace(input_tokens=6000, output_tokens=70))
        self.assertEqual(screen.screen_page(client, "text", ref="9:2"), (True, "x"))
        self.assertEqual(rows(self.path), [("screen", screen.MODEL, 6000, 70, 0, 0, "9:2")])

    def test_analyze_page_records_and_puts_the_cache_breakpoint_on_the_system_block(self):
        client, create = self.fake_client({"articles": []}, SimpleNamespace(
            input_tokens=5200, output_tokens=255, cache_creation_input_tokens=0, cache_read_input_tokens=4013))
        analyze.analyze_page(client, "Guardian", "page text", ref="9:2")
        system = create.call_args.kwargs["system"]
        self.assertIsInstance(system, list)
        self.assertEqual(system[0]["text"], analyze.SYSTEM_PROMPT)
        self.assertEqual(system[0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(create.call_args.kwargs["tools"], [analyze.ANALYZE_TOOL])  # unchanged: tools sit before system in the cached prefix
        self.assertEqual(rows(self.path)[0][:6], ("analyze", analyze.MODEL, 5200, 255, 0, 4013))


class UsageReportTest(unittest.TestCase):
    def test_cost_prices_cache_reads_at_a_tenth_and_writes_at_125_percent(self):
        # Sonnet: 1M in + 1M out = $12; 1M cache-write = $2.5; 1M cache-read = $0.2
        self.assertAlmostEqual(usage_report.cost_usd("claude-sonnet-5", 1_000_000, 1_000_000, 0, 0), 12.0)
        self.assertAlmostEqual(usage_report.cost_usd("claude-sonnet-5", 0, 0, 1_000_000, 0), 2.5)
        self.assertAlmostEqual(usage_report.cost_usd("claude-sonnet-5", 0, 0, 0, 1_000_000), 0.2)

    def test_an_unknown_model_is_unpriced_not_guessed(self):
        self.assertIsNone(usage_report.cost_usd("some-new-model", 1, 1, 0, 0))


if __name__ == "__main__":
    unittest.main()
