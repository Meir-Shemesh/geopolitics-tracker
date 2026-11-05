"""Stage-1 assignment pass (switch off by default, PROJECT_LOG 4.126). No API, no tracker.db."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.reporting import synthesize as syn  # noqa: E402

ARTICLES = [
    {"id": i, "newspaper": "Guardian", "headline": f"h{i}", "region_topic": "r", "stance_summary": "s", "key_excerpt": "k"}
    for i in range(1, 9)
]


def topic(label, ids):
    return {"topic_label_he": "x", "topic_label_en": label, "category": "security_conflict", "article_ids": list(ids)}


def fake_stage2(client, t, topic_articles):
    return {}, {"topic_label_de": "T", "comparison_text_he": "a" * 60, "comparison_text_en": "b" * 60,
                "comparison_text_de": "c" * 60}


def stage1_usage():
    return {"input_tokens": 1, "output_tokens": 1, "stop_reason": "tool_use"}


def run_day(topics, mapping=None, assign_raises=None, switch=True, audit=None):
    """mapping: what the (mocked) assignment call returns."""
    calls = []

    def fake_assign(client, unassigned, tps, model=syn.MODEL):
        calls.append(([a["id"] for a in unassigned], len(tps)))
        if assign_raises:
            raise assign_raises
        return mapping or {}, {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0,
                               "cache_read_input_tokens": 0}

    stage2_topics = []

    def spy_stage2(client, t, topic_articles):
        stage2_topics.append((t["topic_label_en"], list(t["article_ids"])))
        return fake_stage2(client, t, topic_articles)

    with mock.patch.object(syn, "STAGE1_ASSIGN_PASS", switch), \
            mock.patch.object(syn, "group_articles_into_topics", return_value=(topics, stage1_usage())), \
            mock.patch.object(syn, "assign_unassigned_to_topics", side_effect=fake_assign), \
            mock.patch.object(syn, "write_topic_comparison_with_retry", side_effect=spy_stage2):
        sections, usage = syn.synthesize_day_two_stage(None, ARTICLES, audit_out=audit)
    return sections, usage, calls, stage2_topics


class SwitchTest(unittest.TestCase):
    def test_off_by_default(self):
        self.assertFalse(syn.STAGE1_ASSIGN_PASS)

    def test_off_means_no_extra_call_and_unchanged_topics(self):
        topics = [topic("A", [1, 2, 3, 4, 5, 6])]  # 7, 8 unassigned = 25% -> retry (mock returns same) then accepted
        _, _, calls, stage2 = run_day(topics, mapping={7: 1}, switch=False)
        self.assertEqual(calls, [])
        self.assertEqual(stage2, [("A", [1, 2, 3, 4, 5, 6])])

    def test_on_with_nothing_unassigned_makes_no_call(self):
        _, _, calls, _ = run_day([topic("A", [1, 2, 3, 4, 5, 6, 7, 8])], switch=True)
        self.assertEqual(calls, [])


class AssignTest(unittest.TestCase):
    def test_assigned_articles_join_the_existing_topic_before_stage_2(self):
        audit = {}
        topics = [topic("A", [1, 2, 3, 4]), topic("B", [5, 6])]  # 7, 8 unassigned
        sections, usage, calls, stage2 = run_day(topics, mapping={7: 2, 8: 1}, audit=audit)
        self.assertEqual(calls, [([7, 8], 2)])
        self.assertEqual(dict(stage2), {"A": [1, 2, 3, 4, 8], "B": [5, 6, 7]})
        self.assertEqual(audit["assign_pass"]["assigned"], {"7": "B", "8": "A"})
        self.assertEqual(audit["assign_pass"]["left_unassigned"], [])
        covered = {i for s in sections for i in s["article_ids"]}
        self.assertEqual(covered, set(range(1, 9)))

    def test_none_leaves_the_article_unassigned(self):
        audit = {}
        topics = [topic("A", [1, 2, 3, 4, 5, 6])]
        sections, _, _, stage2 = run_day(topics, mapping={7: 1}, audit=audit)
        self.assertEqual(dict(stage2), {"A": [1, 2, 3, 4, 5, 6, 7]})
        self.assertEqual(audit["assign_pass"]["left_unassigned"], [8])
        self.assertEqual(syn.compute_missing_ids(sections, set(range(1, 9))), {8})

    def test_no_new_topics_and_existing_membership_unchanged(self):
        topics = [topic("A", [1, 2, 3]), topic("B", [4, 5, 6])]
        _, _, _, stage2 = run_day(topics, mapping={7: 1})
        self.assertEqual([t for t, _ in stage2], ["A", "B"])
        self.assertEqual(dict(stage2)["B"], [4, 5, 6])
        self.assertEqual(dict(stage2)["A"][:3], [1, 2, 3])

    def test_a_failing_call_leaves_todays_behaviour(self):
        audit = {}
        topics = [topic("A", [1, 2, 3, 4, 5, 6])]
        sections, _, calls, stage2 = run_day(topics, assign_raises=RuntimeError("boom"), audit=audit)
        self.assertEqual(len(calls), 1)
        self.assertEqual(dict(stage2), {"A": [1, 2, 3, 4, 5, 6]})
        self.assertIn("boom", audit["assign_pass"]["error"])
        self.assertEqual(len(sections), 1)

    def test_usage_of_the_pass_is_logged_as_stage_1(self):
        _, usage, _, _ = run_day([topic("A", [1, 2, 3, 4, 5, 6])], mapping={7: 1})
        # (the mocked grouping is retried once at 25% unassigned, so grouping accounts for two entries)
        self.assertEqual([u["input_tokens"] for u in usage if u["stage"] == 1], [1, 1, 10])


class ParseTest(unittest.TestCase):
    def test_validation(self):
        raw = [
            {"article_id": 7, "topic_number": 2},   # ok
            {"article_id": 8, "topic_number": 0},   # none
            {"article_id": 9, "topic_number": 1},   # not an unassigned article -> ignored
            {"article_id": 7, "topic_number": 1},   # duplicate, first wins
            {"article_id": 10, "topic_number": 99}, # topic does not exist -> ignored
            {"article_id": "x"}, "junk", None,
        ]
        self.assertEqual(syn.parse_assignments(raw, {7, 8, 10}, 3), {7: 2})
        self.assertEqual(syn.parse_assignments("not a list", {7}, 3), {})

    def test_a_topic_number_for_a_nonexistent_topic_is_never_applied(self):
        self.assertEqual(syn.parse_assignments([{"article_id": 7, "topic_number": 4}], {7}, 3), {})


class CallShapeTest(unittest.TestCase):
    def test_request_and_response_handling(self):
        block = SimpleNamespace(type="tool_use", input={"assignments": [{"article_id": 7, "topic_number": 1},
                                                                         {"article_id": 8, "topic_number": 0}]})
        response = SimpleNamespace(
            content=[block], stop_reason="tool_use",
            usage=SimpleNamespace(input_tokens=900, output_tokens=60, cache_creation_input_tokens=0, cache_read_input_tokens=0))
        client = mock.MagicMock()
        client.messages.create.return_value = response
        topics = [topic("A", [1, 2]), topic("B", [3])]
        with mock.patch.object(syn, "record_api_usage") as rec:
            mapping, usage = syn.assign_unassigned_to_topics(client, [ARTICLES[6], ARTICLES[7]], topics)
        self.assertEqual(mapping, {7: 1})
        kwargs = client.messages.create.call_args.kwargs
        self.assertEqual(kwargs["tool_choice"], {"type": "tool", "name": "record_assignments"})
        self.assertIn("1. A (2 articles)", kwargs["messages"][0]["content"])
        self.assertIn("id=7", kwargs["messages"][0]["content"])
        self.assertEqual(rec.call_args.args[0], "synthesize_stage1_assign")
        self.assertEqual(usage["output_tokens"], 60)


if __name__ == "__main__":
    unittest.main()
