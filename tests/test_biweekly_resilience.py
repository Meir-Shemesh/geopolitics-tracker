"""Retry-on-transient-error and map/reduce checkpoints in synthesize_biweekly
(PROJECT_LOG 4.100). No API, no tracker.db: the network failure is simulated."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import anthropic
import httpx2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.reporting import synthesize_biweekly as sb  # noqa: E402


class RetryTest(unittest.TestCase):
    def run_with(self, errors, result="ok"):
        calls = []

        def fn():
            calls.append(1)
            if len(calls) <= len(errors):
                raise errors[len(calls) - 1]
            return result

        with mock.patch.object(sb.time, "sleep") as sleep:
            try:
                out = sb.call_with_retry("test", fn)
            except Exception as exc:  # noqa: BLE001
                out = exc
        return out, len(calls), [c.args[0] for c in sleep.call_args_list]

    def test_raw_httpx2_read_error_is_retried_with_backoff(self):
        out, calls, sleeps = self.run_with([httpx2.ReadError("[WinError 10054]"), httpx2.ReadError("again")])
        self.assertEqual((out, calls, sleeps), ("ok", 3, [15, 60]))

    def test_connection_reset_and_sdk_connection_error_are_retried(self):
        req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        out, calls, _ = self.run_with([ConnectionResetError(), anthropic.APIConnectionError(request=req)])
        self.assertEqual((out, calls), ("ok", 3))

    def test_gives_up_after_three_attempts_and_raises_the_last_error(self):
        out, calls, _ = self.run_with([httpx2.ReadError("a"), httpx2.ReadError("b"), httpx2.ReadError("c")])
        self.assertIsInstance(out, httpx2.ReadError)
        self.assertEqual(calls, 3)

    def test_non_transient_error_is_raised_immediately(self):
        out, calls, sleeps = self.run_with([ValueError("logic bug")])
        self.assertIsInstance(out, ValueError)
        self.assertEqual((calls, sleeps), (1, []))


class CheckpointTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(sb, "CHECKPOINT_DIR", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_round_trip(self):
        path = sb._checkpoint_path("2026-10-01", "2026-10-14", "map1", "abc")
        sb.save_checkpoint(path, [{"topic_label_en": "x", "section_ids": [1, 2]}], {"input_tokens": 5, "output_tokens": 6}, 0)
        got = sb.load_checkpoint(path)
        self.assertEqual(got["topics"], [{"topic_label_en": "x", "section_ids": [1, 2]}])
        self.assertEqual(got["usage"]["input_tokens"], 5)

    def test_missing_or_corrupt_checkpoint_is_no_checkpoint(self):
        path = sb._checkpoint_path("2026-10-01", "2026-10-14", "map1", "abc")
        self.assertIsNone(sb.load_checkpoint(path))
        path.write_text("{not json", encoding="utf-8")
        self.assertIsNone(sb.load_checkpoint(path))

    def test_key_changes_when_content_prompt_or_model_changes(self):
        base = sb._content_key("m", "prompt", {"t": 1}, "content")
        self.assertEqual(base, sb._content_key("m", "prompt", {"t": 1}, "content"))
        for changed in (("m2", "prompt", {"t": 1}, "content"), ("m", "prompt2", {"t": 1}, "content"),
                        ("m", "prompt", {"t": 2}, "content"), ("m", "prompt", {"t": 1}, "content2")):
            self.assertNotEqual(base, sb._content_key(*changed))

    def test_clear_removes_only_that_period(self):
        for s, e in (("2026-10-01", "2026-10-14"), ("2026-10-15", "2026-10-28")):
            sb.save_checkpoint(sb._checkpoint_path(s, e, "reduce", "k"), [], {}, 0)
        self.assertEqual(sb.clear_checkpoints("2026-10-01", "2026-10-14"), 1)
        self.assertEqual(len(list(Path(self.tmp.name).glob("*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
