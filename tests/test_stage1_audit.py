"""Stage-1 grouping audit in synthesize.py (PROJECT_LOG 4.114): record-only, never changes a result,
never stops a run. No API, no tracker.db."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.reporting import synthesize as syn  # noqa: E402

ARTICLES = [{"id": i, "newspaper": "Guardian"} for i in range(1, 7)]


def topic(label, ids):
    return {"topic_label_he": "x", "topic_label_en": label, "category": "security_conflict", "article_ids": ids}


def fake_stage2(client, t, topic_articles):
    return {}, {"topic_label_de": "T", "comparison_text_he": "a" * 60, "comparison_text_en": "b" * 60,
                "comparison_text_de": "c" * 60}


def usage(out=100, stop="tool_use"):
    return {"input_tokens": 500, "output_tokens": out, "stop_reason": stop}


def run_day(stage1_returns, audit_out=None):
    with mock.patch.object(syn, "group_articles_into_topics", side_effect=stage1_returns), \
            mock.patch.object(syn, "write_topic_comparison_with_retry", side_effect=fake_stage2):
        return syn.synthesize_day_two_stage(None, ARTICLES, audit_out=audit_out)


class AuditContentTest(unittest.TestCase):
    def test_unassigned_and_multi_assigned_ids_are_recorded(self):
        topics = [topic("A", [1, 2, 3]), topic("B", [3, 4])]  # 3 twice, 5 and 6 unassigned: 3/6 = 50% -> retry
        retry = [topic("A", [1, 2, 3]), topic("B", [4])]  # 5, 6 unassigned: 2/6 = 33%, better -> chosen
        audit = {}
        run_day([(topics, usage(7132, "end_turn")), (retry, usage(90))], audit)
        self.assertTrue(audit["retried"])
        self.assertEqual(audit["chosen_attempt"], 1)
        first, second = audit["attempts"]
        self.assertEqual(first["unassigned_ids"], [5, 6])
        self.assertEqual(first["multi_assigned"], {"3": ["A", "B"]})
        self.assertEqual(first["output_tokens"], 7132)
        self.assertEqual(first["stop_reason"], "end_turn")
        self.assertEqual(first["max_tokens"], 20000)
        self.assertEqual(second["unassigned_ids"], [5, 6])
        self.assertEqual(second["multi_assigned"], {})
        self.assertEqual(audit["article_count"], 6)
        self.assertEqual(audit["threshold"], 0.20)
        self.assertEqual(audit["attempts"][0]["topics"][0], {"label": "A", "article_ids": [1, 2, 3]})

    def test_a_retry_that_does_not_improve_keeps_attempt_zero(self):
        worse = [topic("A", [1])]
        first = [topic("A", [1, 2, 3, 4])]  # 2 unassigned = 33% > 20% -> retry; retry is worse
        audit = {}
        run_day([(first, usage()), (worse, usage())], audit)
        self.assertEqual(audit["chosen_attempt"], 0)

    def test_single_attempt_when_below_threshold(self):
        audit = {}
        run_day([([topic("A", [1, 2, 3, 4, 5, 6])], usage())], audit)
        self.assertFalse(audit["retried"])
        self.assertEqual(len(audit["attempts"]), 1)
        self.assertEqual(audit["attempts"][0]["unassigned_ids"], [])

    def test_empty_topics_are_listed(self):
        audit = {}
        run_day([([topic("A", [1, 2, 3, 4, 5, 6]), topic("junk", [])], usage())], audit)
        self.assertEqual(audit["dropped_empty_topics"], ["junk"])

    def test_a_non_string_stop_reason_is_stored_as_none(self):
        audit = {}
        run_day([([topic("A", [1, 2, 3, 4, 5, 6])], usage(stop=mock.MagicMock()))], audit)
        self.assertIsNone(audit["attempts"][0]["stop_reason"])
        json.dumps(audit)  # must be serialisable


class NoBehaviourChangeTest(unittest.TestCase):
    def test_results_are_identical_with_and_without_the_audit(self):
        topics = [topic("A", [1, 2, 3]), topic("B", [4, 5])]  # 6 unassigned: 17%, no retry
        plain, plain_usage = run_day([(topics, usage())])
        audited, audited_usage = run_day([(topics, usage())], {})
        self.assertEqual(plain, audited)
        self.assertEqual(plain_usage, audited_usage)

    def test_a_broken_audit_record_never_stops_the_run(self):
        topics = [topic("A", [1, 2, 3, 4, 5, 6])]
        with mock.patch.object(syn, "_stage1_attempt_record", side_effect=RuntimeError("boom")):
            audit = {}
            sections, _ = run_day([(topics, usage())], audit)
        self.assertEqual(len(sections), 1)
        self.assertEqual(audit, {})  # nothing recorded, nothing raised

    def test_no_audit_dict_means_no_audit(self):
        sections, _ = run_day([([topic("A", [1, 2, 3, 4, 5, 6])], usage())])
        self.assertEqual(len(sections), 1)


class WriterTest(unittest.TestCase):
    def test_writes_json_next_to_the_review_flags(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            with mock.patch.object(syn, "PROJECT_ROOT", Path(tmp)):
                syn.write_stage1_audit("2026-11-05", {"final_fallback_ids": [1, 2], "note": "ש"})
            out = Path(tmp) / "data" / "processed" / "review_flags" / "2026-11-05.stage1.json"
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["final_fallback_ids"], [1, 2])
            self.assertFalse((out.parent / "2026-11-05.txt").exists())  # the flags file is not touched

    def test_a_write_failure_never_raises(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            blocker = Path(tmp) / "data"
            blocker.write_text("a file where a directory must go", encoding="utf-8")
            with mock.patch.object(syn, "PROJECT_ROOT", Path(tmp)):
                syn.write_stage1_audit("2026-11-05", {"x": 1})  # must not raise


if __name__ == "__main__":
    unittest.main()
