"""The biweekly reduce pass and the overnight wrapper around it (the failed run of 2026-11-05).

No API, no tracker.db, no git: the model call, the database and the subprocess steps are replaced by fakes.
"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from src.reporting import synthesize_biweekly as sb  # noqa: E402
import biweekly_autorun as ba  # noqa: E402


def fake_response(topics, stop_reason="tool_use", output_tokens=1000):
    block = SimpleNamespace(type="tool_use", input={"topics": topics} if topics is not None else {})
    usage = SimpleNamespace(input_tokens=100, output_tokens=output_tokens,
                            cache_creation_input_tokens=0, cache_read_input_tokens=0)
    return SimpleNamespace(content=[block], stop_reason=stop_reason, usage=usage)


class FakeClient:
    """client.messages.stream(**kw) as a context manager whose get_final_message() pops the next canned response."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.messages = self

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        resp = self.responses.pop(0)
        stream = mock.MagicMock()
        stream.__enter__.return_value = stream
        stream.get_final_message.return_value = resp
        return stream


def sections(n):
    return {i: {"id": i, "report_date": "2026-11-01", "topic_label_en": f"t{i}", "comparison_text_en": "x"} for i in range(1, n + 1)}


class ReduceTruncationTest(unittest.TestCase):
    def setUp(self):
        for target in ("count_tokens",):
            p = mock.patch.object(sb, target, return_value=150000)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(sb, "record_usage")
        p.start()
        self.addCleanup(p.stop)

    def run_reduce(self, client, n_sections=6):
        secs = sections(n_sections)
        map_results = [("W1", [{"topic_label_en": "a", "section_ids": list(secs)}])]
        return sb.run_reduce(client, map_results, secs)

    def test_near_ceiling_warning_only_above_75_percent(self):
        limit = sb.REDUCE_MAX_TOKENS
        self.assertIsNone(sb.reduce_ceiling_warning(int(limit * 0.74)))
        self.assertIn("NEAR CEILING", sb.reduce_ceiling_warning(int(limit * 0.75)))

    def test_warning_is_printed_but_does_not_change_the_result(self):
        ids = [{"topic_label_en": "a", "section_ids": [1, 2, 3, 4, 5, 6]}]
        client = FakeClient([fake_response(ids, output_tokens=int(sb.REDUCE_MAX_TOKENS * 0.8))])
        with mock.patch("builtins.print") as printed:
            topics, _, retries = self.run_reduce(client)
        self.assertEqual((len(topics), retries), (1, 0))
        self.assertTrue(any("REDUCE OUTPUT NEAR CEILING" in str(c.args[0]) for c in printed.call_args_list))

    def test_ceiling_is_above_the_old_one_and_is_what_the_request_uses(self):
        self.assertGreater(sb.REDUCE_MAX_TOKENS, 24000)
        ids = [{"topic_label_en": "a", "section_ids": [1, 2, 3, 4, 5, 6]}]
        client = FakeClient([fake_response(ids)])
        topics, _, retries = self.run_reduce(client)
        self.assertEqual((len(topics), retries), (1, 0))
        self.assertEqual(client.calls[0]["max_tokens"], sb.REDUCE_MAX_TOKENS)

    def test_truncation_at_max_tokens_raises_without_a_futile_retry(self):
        client = FakeClient([fake_response(None, stop_reason="max_tokens", output_tokens=sb.REDUCE_MAX_TOKENS)])
        with self.assertRaises(sb.ReduceFailedError) as ctx:
            self.run_reduce(client)
        self.assertEqual(len(client.calls), 1)
        self.assertIn("cut off", str(ctx.exception))

    def test_empty_result_raises_instead_of_returning_an_empty_grouping(self):
        client = FakeClient([fake_response([]), fake_response([])])
        with self.assertRaises(sb.ReduceFailedError):
            self.run_reduce(client)

    def test_retry_that_is_itself_truncated_is_not_used(self):
        partial = [{"topic_label_en": "a", "section_ids": [1, 2, 3]}]  # 3 of 6 missing -> over the threshold
        client = FakeClient([fake_response(partial), fake_response(None, stop_reason="max_tokens")])
        topics, _, retries = self.run_reduce(client)
        self.assertEqual((topics, retries), (partial, 1))

    def test_input_far_above_the_old_volume_still_builds_one_request(self):
        # 878 groups (5.11) -> well over the 626 / 107K-token volume that first worked.
        secs = sections(1175)
        groups = [{"topic_label_en": f"g{i}", "section_ids": [i + 1]} for i in range(878)]
        n, content = sb.reduce_user_content([("W1", groups)], secs)
        self.assertEqual(n, 878)
        self.assertIn("(878 total)", content)


class CheckpointGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(sb, "CHECKPOINT_DIR", Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)

    def test_an_empty_checkpoint_on_disk_is_ignored(self):
        path = sb._checkpoint_path("2026-10-22", "2026-11-04", "reduce", "abc")
        sb.save_checkpoint(path, [], {"input_tokens": 1, "output_tokens": 1}, 1)
        self.assertTrue(path.exists())
        self.assertIsNone(sb.load_checkpoint(path))

    def test_failed_reduce_leaves_no_reduce_checkpoint_but_keeps_map_checkpoints(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE report_sections (id INTEGER, report_date TEXT, topic_label_en TEXT, "
                     "comparison_text_en TEXT, category TEXT)")
        for i in (1, 2):
            conn.execute("INSERT INTO report_sections VALUES (?, '2026-11-01', 'l', 'c', 'x')", (i,))
        map_topics = [{"topic_label_en": "a", "section_ids": [1, 2]}]
        with mock.patch.object(sb, "build_windows", return_value=[["2026-11-01"]]), \
                mock.patch.object(sb, "run_map", return_value=(map_topics, {"input_tokens": 1, "output_tokens": 1}, 0)), \
                mock.patch.object(sb, "run_reduce", side_effect=sb.ReduceFailedError("cut off")):
            with self.assertRaises(sb.ReduceFailedError):
                sb.run_stage1(None, conn, "2026-10-22", "2026-11-04")
        names = sorted(p.name for p in Path(self.tmp.name).glob("*.json"))
        self.assertEqual(len(names), 1)
        self.assertIn("_map1_", names[0])


class MainExitCodeTest(unittest.TestCase):
    def run_main(self, **patches):
        argv = ["synthesize_biweekly", "--start", "2026-10-22", "--end", "2026-11-04"]
        conn = mock.MagicMock()
        stack = mock.patch.multiple(
            sb, get_connection=mock.DEFAULT, init_db=mock.DEFAULT, get_report_dates_in_range=mock.DEFAULT,
            missing_published_days=mock.DEFAULT, biweekly_period_exists=mock.DEFAULT, **{k: v for k, v in patches.items()})
        with mock.patch.object(sys, "argv", argv), mock.patch.object(sb.anthropic, "Anthropic"), stack as m:
            m["get_connection"].return_value = conn
            m["missing_published_days"].return_value = []
            m["biweekly_period_exists"].return_value = False
            return sb.main()

    def test_reduce_failure_exits_with_its_own_code(self):
        code = self.run_main(run_stage1=mock.Mock(side_effect=sb.ReduceFailedError("cut off")))
        self.assertEqual(code, sb.EXIT_REDUCE_FAILED)

    def test_no_grouped_topics_is_an_error_exit(self):
        self.assertEqual(self.run_main(run_stage1=mock.Mock(return_value=[])), sb.EXIT_NO_TOPICS)

    def test_no_topic_clearing_the_threshold_is_an_error_exit(self):
        code = self.run_main(run_stage1=mock.Mock(return_value=[{"n_distinct_days": 1}]),
                             load_topics_for_stage2=mock.Mock(return_value=[]))
        self.assertEqual(code, sb.EXIT_NO_TOPICS)


class AutorunNoCommitOnFailureTest(unittest.TestCase):
    def run_autorun(self, synth_ok, wrote_period):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        steps = []

        def run_step(log, name, args, timeout_key=None):
            steps.append(name)
            ok = synth_ok if name == "synthesize_biweekly" else True
            return ba.autorun.StepResult(name, ok, 0 if ok else 3, "", "")

        git = mock.Mock(return_value=(True, "committed and pushed"))
        emails = []
        with mock.patch.object(sys, "argv", ["biweekly_autorun", "--as-of", "2026-11-05"]), \
                mock.patch.object(ba, "STATE_FILE", d / "state.json"), \
                mock.patch.object(ba, "KILLSWITCH_FLAG", d / "kill.flag"), \
                mock.patch.object(ba, "PAUSE_NEXT_FLAG", d / "pause.flag"), \
                mock.patch.object(ba.autorun, "LOG_DIR", d), \
                mock.patch.object(ba.autorun, "load_env"), \
                mock.patch.object(ba.autorun, "run_step", run_step), \
                mock.patch.object(ba.autorun, "do_git_sequence", git), \
                mock.patch.object(ba.autorun, "send_email", lambda s, b: emails.append(s)), \
                mock.patch.object(ba, "get_connection", return_value=mock.MagicMock()), \
                mock.patch.object(ba, "missing_days_problem", return_value=None), \
                mock.patch.object(ba, "notify_started", return_value=True), \
                mock.patch.object(ba, "biweekly_period_exists", side_effect=[False, wrote_period]):
            code = ba.main()
        return code, steps, git, emails

    def test_no_period_row_means_no_publish_no_commit_and_a_failure_email(self):
        code, steps, git, emails = self.run_autorun(synth_ok=True, wrote_period=False)
        self.assertEqual(code, 1)
        self.assertEqual(steps, ["synthesize_biweekly"])
        git.assert_not_called()
        self.assertTrue(any("FAILED" in s for s in emails))

    def test_synthesize_failing_stops_before_publish_and_git(self):
        code, steps, git, emails = self.run_autorun(synth_ok=False, wrote_period=False)
        self.assertEqual((code, steps), (1, ["synthesize_biweekly"]))
        git.assert_not_called()

    def test_a_written_period_still_publishes_and_commits(self):
        code, steps, git, emails = self.run_autorun(synth_ok=True, wrote_period=True)
        self.assertEqual((code, steps), (0, ["synthesize_biweekly", "publish"]))
        git.assert_called_once()
        self.assertTrue(any("published" in s for s in emails))


if __name__ == "__main__":
    unittest.main()
