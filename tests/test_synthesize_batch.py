"""synthesize.py stage 2 with SYNTH_USE_BATCH (Message Batches API, PROJECT_LOG 4.136).

No API and no real database: the client is a fake implementing just the batches calls the code uses, the regular
call (write_topic_comparison) is a spy, and api_batches lives in a temporary SQLite file.
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.common import db
from src.reporting import synthesize

USAGE = dict(input_tokens=1000, output_tokens=300, cache_creation_input_tokens=0, cache_read_input_tokens=3900)
GOOD = {
    "topic_label_de": "Thema",
    "comparison_text_he": "השוואה בעברית שהיא מספיק ארוכה כדי לא להיחשב חשודה בשום צורה.",
    "comparison_text_en": "A comparison in English that is long enough not to look suspicious in any way at all.",
    "comparison_text_de": "Ein Vergleich auf Deutsch, der lang genug ist, um in keiner Weise verdächtig zu wirken.",
}


def ok_entry(custom_id, tool_input=None):
    content = [SimpleNamespace(type="tool_use", input=dict(tool_input or GOOD))]
    return SimpleNamespace(custom_id=custom_id, result=SimpleNamespace(
        type="succeeded", message=SimpleNamespace(content=content, usage=SimpleNamespace(**USAGE), stop_reason="tool_use")))


def other_entry(custom_id, kind):
    return SimpleNamespace(custom_id=custom_id, result=SimpleNamespace(type=kind, error=SimpleNamespace(message=kind)))


class FakeBatches:
    def __init__(self, plan=None, behaviour="ok"):
        self.plan = plan or (lambda cid: ok_entry(cid))
        self.behaviour = behaviour  # ok | never_ends | create_fails | results_fail
        self.created: list[tuple[str, list[dict]]] = []
        self.canceled: list[str] = []

    def create(self, requests):
        if self.behaviour == "create_fails":
            raise RuntimeError("503 overloaded")
        batch_id = f"msgbatch_{len(self.created) + 1}"
        self.created.append((batch_id, requests))
        return SimpleNamespace(id=batch_id)

    def retrieve(self, batch_id):
        ended = self.behaviour in ("ok", "results_fail") or batch_id in self.canceled
        counts = SimpleNamespace(processing=0 if ended else 1, succeeded=0, errored=0, canceled=0, expired=0)
        return SimpleNamespace(processing_status="ended" if ended else "in_progress", request_counts=counts)

    def cancel(self, batch_id):
        self.canceled.append(batch_id)

    def results(self, batch_id):
        if self.behaviour == "results_fail":
            raise RuntimeError("results unavailable")
        out = []
        for created_id, requests in self.created:
            if created_id != batch_id:
                continue
            for request in requests:
                entry = self.plan(request["custom_id"])
                if entry is None and batch_id in self.canceled:
                    entry = other_entry(request["custom_id"], "canceled")
                if entry is not None:
                    out.append(entry)
        return out


def make_topic(n):
    return {"topic_label_en": f"Topic {n}", "topic_label_he": f"נושא {n}", "category": "diplomacy_international",
            "article_ids": [n * 10, n * 10 + 1]}


def make_article(i, newspaper):
    return {"id": i, "newspaper": newspaper, "headline": f"H{i}", "region_topic": "r", "stance_summary": "s",
            "key_excerpt": "k", "author": ""}


class StageTwoBatchTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self._tmp.name) / "t.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        db.init_db(self.conn)
        self.regular_calls: list[str] = []
        self.regular_plan = lambda topic: dict(GOOD)
        env = mock.patch.dict(os.environ, {"TRACKER_NO_USAGE_LOG": "1"})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self.conn.close)

        def fake_regular(client, topic, topic_articles, feedback=None):
            self.regular_calls.append(topic["topic_label_en"] + ("|fb" if feedback else ""))
            result = self.regular_plan(topic)
            if isinstance(result, Exception):
                raise result
            return dict(USAGE), result

        p = mock.patch.object(synthesize, "write_topic_comparison", side_effect=fake_regular)
        p.start()
        self.addCleanup(p.stop)
        self.articles_by_id = {i: make_article(i, "The Guardian" if i % 2 else "Der Spiegel") for n in range(1, 8) for i in (n * 10, n * 10 + 1)}

    def run_stage(self, topics, batches, timeout=60):
        client = SimpleNamespace(messages=SimpleNamespace(batches=batches))
        by_id = self.articles_by_id
        with mock.patch.object(synthesize, "group_articles_into_topics",
                               return_value=([dict(t) for t in topics], dict(USAGE, stage=1))):
            return synthesize.synthesize_day_two_stage(
                client, list(by_id.values()), batch_conn=self.conn, batch_timeout_seconds=timeout)

    def test_request_is_the_regular_request(self):
        topic = make_topic(1)
        arts = [self.articles_by_id[10], self.articles_by_id[11]]
        params = synthesize.build_stage2_params(topic, arts)
        batches = FakeBatches()
        self.run_stage([topic], batches)
        sent = batches.created[0][1][0]["params"]
        self.assertEqual(sent, params)
        self.assertEqual(sent["tool_choice"], {"type": "tool", "name": "record_topic_comparison"})
        self.assertNotIn("thinking", sent)

    def test_all_topics_answered_by_batch_no_regular_calls(self):
        topics = [make_topic(n) for n in (1, 2, 3)]
        batches = FakeBatches()
        sections, usage_log = self.run_stage(topics, batches)
        self.assertEqual(len(sections), 3)
        self.assertEqual(self.regular_calls, [])
        self.assertEqual(len(batches.created), 1)
        self.assertEqual(len([u for u in usage_log if u["stage"] == 2]), 3)
        row = self.conn.execute("SELECT * FROM api_batches").fetchone()
        self.assertEqual((row["stage"], row["status"]), ("synthesize", "collected"))

    def test_row_is_stored_before_waiting(self):
        seen = {}
        batches = FakeBatches()
        original = batches.retrieve

        def spying(batch_id):
            c = sqlite3.connect(self.db_path)
            seen[batch_id] = c.execute("SELECT status FROM api_batches WHERE batch_id = ?", (batch_id,)).fetchone()
            c.close()
            return original(batch_id)

        batches.retrieve = spying
        self.run_stage([make_topic(1)], batches)
        self.assertEqual(seen["msgbatch_1"][0], "submitted")

    def test_batch_usage_is_logged_as_half_price_stage(self):
        os.environ.pop("TRACKER_NO_USAGE_LOG")
        with mock.patch.object(db, "DB_PATH", self.db_path):
            self.run_stage([make_topic(1)], FakeBatches())
        row = self.conn.execute("SELECT stage FROM api_usage").fetchone()
        self.assertEqual(row["stage"], "synthesize_stage2_batch")
        self.assertTrue(db.is_batch_stage(row["stage"]))

    def test_failed_topics_take_regular_calls(self):
        topics = [make_topic(n) for n in (1, 2, 3, 4)]
        kinds = {"s2-1": "errored", "s2-2": "expired"}

        def plan(cid):
            return other_entry(cid, kinds[cid]) if cid in kinds else ok_entry(cid)

        sections, _ = self.run_stage(topics, FakeBatches(plan))
        self.assertEqual(len(sections), 4)
        self.assertEqual(sorted(self.regular_calls), ["Topic 2", "Topic 3"])

    def test_malformed_answer_takes_regular_call(self):
        def plan(cid):
            return ok_entry(cid, {"topic_label_de": "x", "comparison_text_he": "a"}) if cid == "s2-0" else ok_entry(cid)

        sections, _ = self.run_stage([make_topic(1), make_topic(2)], FakeBatches(plan))
        self.assertEqual(len(sections), 2)
        self.assertEqual(self.regular_calls, ["Topic 1"])

    def test_suspicious_batch_answer_gets_the_regular_retry(self):
        bad = dict(GOOD, comparison_text_he="0")
        batches = FakeBatches(lambda cid: ok_entry(cid, bad))
        sections, _ = self.run_stage([make_topic(1)], batches)
        self.assertEqual(self.regular_calls, ["Topic 1"])  # the second attempt is the regular call
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["comparison_text_he"], GOOD["comparison_text_he"])

    def test_suspicious_twice_is_dropped_to_fallback(self):
        bad = dict(GOOD, comparison_text_he="0")
        self.regular_plan = lambda topic: dict(bad)
        sections, _ = self.run_stage([make_topic(1)], FakeBatches(lambda cid: ok_entry(cid, bad)))
        self.assertEqual(sections, [])

    def test_hebrew_letter_newspaper_name_gets_feedback_rewrite(self):
        bad = dict(GOOD, comparison_text_he=GOOD["comparison_text_he"] + " בטלגרף נכתב כך.")
        calls = []

        def regular(topic):
            calls.append(1)
            return dict(GOOD)

        self.regular_plan = regular
        sections, _ = self.run_stage([make_topic(1)], FakeBatches(lambda cid: ok_entry(cid, bad)))
        self.assertEqual(self.regular_calls, ["Topic 1|fb"])
        self.assertEqual(sections[0]["comparison_text_he"], GOOD["comparison_text_he"])

    def test_timeout_cancels_and_falls_back_for_every_topic(self):
        batches = FakeBatches(plan=lambda cid: None, behaviour="never_ends")
        with mock.patch.object(synthesize, "SYNTH_BATCH_POLL_SECONDS", 0.001):
            sections, _ = self.run_stage([make_topic(n) for n in (1, 2)], batches, timeout=0.05)
        self.assertEqual(len(sections), 2)
        self.assertEqual(sorted(self.regular_calls), ["Topic 1", "Topic 2"])
        self.assertEqual(batches.canceled, ["msgbatch_1"])
        self.assertEqual(self.conn.execute("SELECT status FROM api_batches").fetchone()[0], "collected")

    def test_unreadable_results_abandon_the_batch_and_fall_back(self):
        sections, _ = self.run_stage([make_topic(1), make_topic(2)], FakeBatches(behaviour="results_fail"))
        self.assertEqual(len(sections), 2)
        self.assertEqual(len(self.regular_calls), 2)
        self.assertEqual(self.conn.execute("SELECT status FROM api_batches").fetchone()[0], "abandoned")

    def test_create_failure_falls_back_to_regular_path(self):
        sections, _ = self.run_stage([make_topic(1), make_topic(2)], FakeBatches(behaviour="create_fails"))
        self.assertEqual(len(sections), 2)
        self.assertEqual(len(self.regular_calls), 2)

    def test_left_open_batch_is_canceled_and_closed(self):
        db.insert_api_batch(self.conn, "msgbatch_old", "synthesize", synthesize.MODEL, ["s2-0"])
        batches = FakeBatches()
        batches.created.append(("msgbatch_old", []))  # unknown to the fake otherwise; cancel only records the call
        self.run_stage([make_topic(1)], batches)
        self.assertIn("msgbatch_old", batches.canceled)
        statuses = {r["batch_id"]: r["status"] for r in self.conn.execute("SELECT * FROM api_batches")}
        self.assertEqual(statuses["msgbatch_old"], "abandoned")

    def test_regular_path_is_untouched_without_batch_conn(self):
        topics = [make_topic(1), make_topic(2)]
        batches = FakeBatches()
        client = SimpleNamespace(messages=SimpleNamespace(batches=batches))
        with mock.patch.object(synthesize, "group_articles_into_topics",
                               return_value=([dict(t) for t in topics], dict(USAGE, stage=1))):
            sections, _ = synthesize.synthesize_day_two_stage(client, list(self.articles_by_id.values()))
        self.assertEqual(len(sections), 2)
        self.assertEqual(batches.created, [])
        self.assertEqual(len(self.regular_calls), 2)

    def test_summary_line_with_batch_counts_fallbacks_and_retries(self):
        topics = [make_topic(n) for n in (1, 2, 3, 4)]
        kinds = {"s2-1": "errored", "s2-2": "expired"}
        plan = lambda cid: other_entry(cid, kinds[cid]) if cid in kinds else ok_entry(cid)
        self.run_stage(topics, FakeBatches(plan))
        line = synthesize.format_stage2_summary(synthesize.STAGE2_RUN_INFO, synthesize.STAGE2_EVENTS, 0.85)
        for part in ("topics=4", "batch=2", "fell_to_regular=2", "failed_topics=0", "stage2_cost=$0.85"):
            self.assertIn(part, line)

    def test_summary_line_counts_retry_kinds_and_failed_topics(self):
        bad = dict(GOOD, comparison_text_he="0")
        self.regular_plan = lambda topic: dict(bad)
        self.run_stage([make_topic(1)], FakeBatches(lambda cid: ok_entry(cid, bad)))
        self.assertEqual(synthesize.STAGE2_EVENTS["suspicious"], 1)
        self.assertEqual(synthesize.STAGE2_EVENTS["failed_topic"], 1)
        line = synthesize.format_stage2_summary(synthesize.STAGE2_RUN_INFO, synthesize.STAGE2_EVENTS, None)
        self.assertIn("suspicious=1", line)
        self.assertIn("stage2_cost=n/a", line)

    def test_summary_line_with_batch_off_does_not_crash(self):
        topics = [make_topic(1), make_topic(2)]
        client = SimpleNamespace(messages=SimpleNamespace(batches=FakeBatches()))
        with mock.patch.object(synthesize, "group_articles_into_topics",
                               return_value=([dict(t) for t in topics], dict(USAGE, stage=1))):
            synthesize.synthesize_day_two_stage(client, list(self.articles_by_id.values()))
        line = synthesize.format_stage2_summary(synthesize.STAGE2_RUN_INFO, synthesize.STAGE2_EVENTS, 0.0)
        self.assertIn("topics=2", line)
        self.assertIn("batch=off", line)
        self.assertNotIn("fell_to_regular", line)

    def test_cli_help_builds(self):
        """The 2026-11-10 daily run crashed on `python -m src.reporting.synthesize` because a '%' in a help string breaks
        argparse; no test ran the real parser. --help builds every argument, so it fails the same way."""
        import subprocess, sys
        result = subprocess.run([sys.executable, "-m", "src.reporting.synthesize", "--help"], cwd=str(Path(__file__).resolve().parents[1]),
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        self.assertIn("--batch", result.stdout)

    def test_defaults_are_locked(self):
        """Batch is OFF by default again (2026-11-10, after the CLI crash) until Meir approves, and the wrapper's ceiling
        must cover the worst case: stage 1 (5) + batch wait + cancel (2) + a full regular stage 2 (15) minutes."""
        from scripts import daily_autorun
        self.assertFalse(synthesize.SYNTH_USE_BATCH)
        worst_case_minutes = 5 + synthesize.SYNTH_BATCH_TIMEOUT_SECONDS / 60 + 2 + 15
        self.assertGreaterEqual(daily_autorun.TIMEOUTS["synthesize"] / 60, worst_case_minutes)
        self.assertEqual(daily_autorun.TIMEOUTS["synthesize"], 45 * 60)


if __name__ == "__main__":
    unittest.main()
