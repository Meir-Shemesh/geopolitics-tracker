"""Stage-1 output-ceiling warning and the Hebrew newspaper-name retry in synthesize.py (PROJECT_LOG 4.113)."""

import unittest
from types import SimpleNamespace
from unittest import mock

from src.reporting import synthesize as syn

LONG = "טקסט השוואה ארוך מספיק כדי לא להיחשב חשוד, " * 4
EN = "A long enough English comparison text that is not considered suspicious by the output guard. " * 2
DE = "Ein ausreichend langer deutscher Vergleichstext, der vom Ausgabe-Schutz nicht als verdächtig gilt. " * 2


def comparison(label_he="חברון", text_he=LONG):
    return {
        "topic_label_he": label_he, "topic_label_en": "Hebron", "topic_label_de": "Hebron",
        "comparison_text_he": text_he, "comparison_text_en": EN, "comparison_text_de": DE,
    }


class Stage1CeilingTest(unittest.TestCase):
    def test_ceiling_is_raised_but_stays_under_the_non_streaming_cutoff(self):
        self.assertEqual(syn.STAGE1_MAX_TOKENS, 20000)
        self.assertLess(syn.STAGE1_MAX_TOKENS, 21333)

    def test_the_466_article_day_is_quiet(self):
        self.assertIsNone(syn.stage1_ceiling_warning(13970, "end_turn"))  # 2026-10-30, 70% of the new ceiling

    def test_warning_starts_at_85_percent(self):
        self.assertIsNone(syn.stage1_ceiling_warning(16999, "end_turn"))
        self.assertIn("NEAR CEILING", syn.stage1_ceiling_warning(17000, "end_turn"))

    def test_hitting_the_ceiling_is_reported_as_truncation(self):
        self.assertIn("HIT THE CEILING", syn.stage1_ceiling_warning(20000, "max_tokens"))
        self.assertIn("HIT THE CEILING", syn.stage1_ceiling_warning(12000, "max_tokens"))

    def _client(self, output_tokens, stop_reason="end_turn"):
        block = SimpleNamespace(type="tool_use", input={"topics": []})
        usage = SimpleNamespace(input_tokens=10, output_tokens=output_tokens,
                                cache_creation_input_tokens=0, cache_read_input_tokens=0)
        response = SimpleNamespace(content=[block], usage=usage, stop_reason=stop_reason)
        return mock.Mock(**{"messages.create.return_value": response})

    def test_stage1_call_uses_the_new_ceiling_and_carries_the_warning(self):
        client = self._client(17500)
        with mock.patch.object(syn, "record_api_usage"):
            _topics, usage = syn.group_articles_into_topics(client, [])
        self.assertEqual(client.messages.create.call_args.kwargs["max_tokens"], 20000)
        self.assertIn("NEAR CEILING", usage["ceiling_warning"])

    def test_no_warning_key_on_a_normal_day(self):
        with mock.patch.object(syn, "record_api_usage"):
            _topics, usage = syn.group_articles_into_topics(self._client(9000), [])
        self.assertNotIn("ceiling_warning", usage)


class HebrewNameRetryTest(unittest.TestCase):
    TOPIC = {"topic_label_en": "Hebron", "topic_label_he": "חברון"}
    ARTICLES = [{"newspaper": "Daily Telegraph"}, {"newspaper": "Guardian"}]
    BAD = comparison(text_he="טלגרף מציג את הגרסה הרשמית. " + LONG)
    GOOD = comparison(text_he="The Daily Telegraph מציג את הגרסה הרשמית. " + LONG)

    def run_retry(self, retry=None, raises=False, first=None):
        calls = []

        def fake(client, topic, arts, feedback=None):
            calls.append(feedback)
            if raises:
                raise RuntimeError("boom")
            return {"input_tokens": 1}, dict(retry)

        first = first or self.BAD
        with mock.patch.object(syn, "write_topic_comparison", side_effect=fake):
            result = syn._retry_for_hebrew_newspaper_names(None, self.TOPIC, self.ARTICLES, {"input_tokens": 0}, dict(first))
        return result, calls

    def test_a_hebrew_letter_name_triggers_one_rewrite_with_named_feedback_and_the_rewrite_is_used(self):
        (usage, comp), calls = self.run_retry(self.GOOD)
        self.assertEqual(len(calls), 1)
        self.assertIn("טלגרף", calls[0])
        self.assertIn("The Daily Telegraph", calls[0])
        self.assertEqual(comp["comparison_text_he"], self.GOOD["comparison_text_he"])

    def test_the_label_is_checked_too(self):
        bad_label = comparison(label_he="טלגרף וגארדיין בחברון")
        (_, comp), calls = self.run_retry(self.GOOD, first=bad_label)
        self.assertEqual(len(calls), 1)
        self.assertIn("גארדיין", calls[0])

    def test_clean_text_makes_no_extra_call(self):
        (_, comp), calls = self.run_retry(self.GOOD, first=self.GOOD)
        self.assertEqual(calls, [])
        self.assertEqual(comp, self.GOOD)

    def test_failed_rewrite_keeps_the_original(self):
        (_, comp), calls = self.run_retry(raises=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(comp, self.BAD)

    def test_a_rewrite_that_still_has_the_name_is_not_used_and_there_is_no_loop(self):
        (_, comp), calls = self.run_retry(self.BAD)
        self.assertEqual(len(calls), 1)
        self.assertEqual(comp, self.BAD)

    def test_a_suspicious_rewrite_is_not_used(self):
        short = comparison(text_he="קצר")
        (_, comp), calls = self.run_retry(short)
        self.assertEqual(comp, self.BAD)

    def test_audit_still_flags_what_stays(self):
        sections = [{"topic_label_en": "x", "article_ids": [1], **self.BAD}]
        flags = syn.audit_sections(sections, [{"id": 1, "newspaper": "Daily Telegraph"}])
        self.assertTrue(any("NEWSPAPER NAME IN HEBREW LETTERS" in f for f in flags))

    def test_wrapper_chains_the_name_retry_after_a_good_first_answer(self):
        answers = iter([self.BAD, self.GOOD])
        with mock.patch.object(syn, "write_topic_comparison", side_effect=lambda *a, **k: ({"input_tokens": 1}, dict(next(answers)))) as w:
            usage, comp = syn.write_topic_comparison_with_retry(None, self.TOPIC, self.ARTICLES)
        self.assertEqual(w.call_count, 2)
        self.assertEqual(comp["comparison_text_he"], self.GOOD["comparison_text_he"])

    def test_wrapper_makes_a_single_call_when_nothing_is_wrong(self):
        with mock.patch.object(syn, "write_topic_comparison", return_value=({"input_tokens": 1}, dict(self.GOOD))) as w:
            syn.write_topic_comparison_with_retry(None, self.TOPIC, self.ARTICLES)
        self.assertEqual(w.call_count, 1)


if __name__ == "__main__":
    unittest.main()
