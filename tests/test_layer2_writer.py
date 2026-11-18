"""Second layer on top of the shared text checks: 10% word-ceiling tolerance, the full rules reminder in every retry, rejected
text saved to review_flags, and the per-topic checkpoint of biweekly stage 2. Mocked API calls only."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")

from src.reporting import synthesize, synthesize_biweekly as sb


def words(n, lang="he"):
    filler = {"he": "מילה", "en": "word", "de": "Wort"}[lang]
    return " ".join([filler] * n)


def result(he=60, en=60, de=60, **extra):
    r = {"topic_label_he": "נושא", "topic_label_en": "Topic", "topic_label_de": "Thema",
         "comparison_text_he": words(he), "comparison_text_en": words(en, "en"), "comparison_text_de": words(de, "de")}
    r.update(extra)
    return r


TOPIC = {"topic_label_en": "Topic", "n_distinct_days": 6, "n_sources": 3}  # tier "developed": ceiling 100, tolerated up to 110


class ToleranceTest(unittest.TestCase):
    def run_topic(self, answers):
        feedbacks = []

        def fake(client, topic, days, feedback=""):
            feedbacks.append(feedback)
            return dict(answers.pop(0)), {"input_tokens": 1, "output_tokens": 1}

        out = io.StringIO()
        with mock.patch.object(sb, "write_biweekly_topic", side_effect=fake), contextlib.redirect_stdout(out):
            sb.BIWEEKLY_REJECTED.clear()
            res = sb.write_biweekly_topic_with_retry(None, TOPIC, [])
        return res, feedbacks, out.getvalue()

    def test_a_text_up_to_ten_percent_over_the_ceiling_is_accepted_without_a_retry_and_logged(self):
        (res, _, over), feedbacks, log = self.run_topic([result(he=60, en=101, de=110)])
        self.assertIsNotNone(res)
        self.assertEqual(len(feedbacks), 1)
        self.assertEqual(over, {})
        self.assertIn("within the 10% tolerance", log)
        self.assertIn("en=101w", log)
        self.assertIn("de=110w", log)

    def test_one_word_beyond_the_tolerance_retries_as_before(self):
        (res, _, over), feedbacks, log = self.run_topic([result(en=111), result()])
        self.assertIsNotNone(res)
        self.assertEqual(len(feedbacks), 2)
        self.assertIn("en was 111 words", feedbacks[1])

    def test_still_over_the_tolerance_after_the_retry_is_kept_and_flagged_as_before(self):
        (res, _, over), feedbacks, log = self.run_topic([result(en=120), result(en=115)])
        self.assertIsNotNone(res)
        self.assertEqual(over, {"en": 115})
        self.assertIn("keeping anyway, flagged", log)

    def test_the_ceiling_in_the_prompt_is_unchanged(self):
        self.assertEqual(sb.WORD_CEILINGS, {"deep": 140, "developed": 100, "concise": 70})
        self.assertIn("Hard limit: 100 words", sb.DEPTH_INSTRUCTIONS["developed"])
        self.assertEqual(sb.over_ceiling_langs(result(en=101), "developed"), {"en": 101})  # strict by default
        self.assertEqual(sb.over_ceiling_langs(result(en=154), "deep", 0.10), {})
        self.assertEqual(sb.over_ceiling_langs(result(en=155), "deep", 0.10), {"en": 155})

    def test_the_12_november_cases_would_not_have_started_a_retry(self):
        # Iran/Hormuz: de=141 against the deep ceiling 140; Venezuela: en=101 against 100
        deep = {"topic_label_en": "Iran", "n_distinct_days": 14, "n_sources": 11}
        self.assertEqual(sb.over_ceiling_langs(result(de=141), "deep", sb.WORD_CEILING_TOLERANCE), {})
        self.assertEqual(sb.over_ceiling_langs(result(en=101), "concise" if False else "developed", sb.WORD_CEILING_TOLERANCE), {})


class RulesReminderTest(unittest.TestCase):
    def test_every_biweekly_retry_restates_all_rules_not_only_the_failed_one(self):
        feedbacks = []

        def fake(client, topic, days, feedback=""):
            feedbacks.append(feedback)
            return dict(result(en=125) if len(feedbacks) == 1 else result()), {"input_tokens": 1, "output_tokens": 1}

        with mock.patch.object(sb, "write_biweekly_topic", side_effect=fake), contextlib.redirect_stdout(io.StringIO()):
            sb.write_biweekly_topic_with_retry(None, TOPIC, [])
        fb = feedbacks[1]
        self.assertIn("en was 125 words", fb)                       # the rule that failed
        self.assertIn("FULL REMINDER OF ALL RULES", fb)             # all the others, although only the ceiling failed
        self.assertIn('"The Globe and Mail"', fb)                   # names, from the canonical list
        self.assertIn("at most 100 words", fb)
        self.assertIn("never a Latin letter inside a Hebrew word", fb)
        self.assertIn("no markup", fb)
        self.assertIn("no spaced hyphen", fb)

    def test_every_daily_retry_feedback_carries_the_reminder(self):
        self.assertIn("FULL REMINDER OF ALL RULES", synthesize.hebrew_name_retry_feedback({"טלגרף": "The Daily Telegraph"}))
        self.assertIn("FULL REMINDER OF ALL RULES", synthesize.framing_retry_feedback({"languages": ["he"], "groups": {"UK": ["A", "B"]}}))
        bad = {"topic_label_de": "T", "comparison_text_he": "נתניהu אמר", "comparison_text_en": "x", "comparison_text_de": "y"}
        self.assertIn("FULL REMINDER OF ALL RULES", synthesize._suspicious_retry_feedback(bad))
        self.assertEqual(synthesize._suspicious_retry_feedback({"topic_label_de": "T", "comparison_text_he": "טקסט תקין לגמרי בעברית",
                                                                "comparison_text_en": "ok", "comparison_text_de": "ok"}), "")


class RejectedTextTest(unittest.TestCase):
    def test_dropped_topic_and_its_first_attempt_are_saved_with_text_and_reasons(self):
        bad = result(he=60)
        bad["comparison_text_he"] += " ואילו גלוב אנד מייל נשאר עובדתי."
        with mock.patch.object(sb, "write_biweekly_topic", side_effect=[(dict(bad), {}), (dict(bad), {})]), \
             contextlib.redirect_stdout(io.StringIO()):
            sb.BIWEEKLY_REJECTED.clear()
            res = sb.write_biweekly_topic_with_retry(None, TOPIC, [])
        self.assertIsNone(res[0])
        outcomes = [(e["attempt"], e["outcome"]) for e in sb.BIWEEKLY_REJECTED]
        self.assertEqual(outcomes, [(1, "retried"), (2, "dropped")])
        self.assertIn("גלוב אנד מייל", sb.BIWEEKLY_REJECTED[1]["text"]["comparison_text_he"])
        self.assertTrue(sb.BIWEEKLY_REJECTED[1]["reasons"][0].startswith("newspaper_names"))
        with tempfile.TemporaryDirectory() as d, mock.patch.object(sb, "REVIEW_FLAGS_DIR", Path(d)):
            line = sb.write_rejected_report("2026-11-18")
            saved = json.loads((Path(d) / "2026-11-18.biweekly_rejected.json").read_text(encoding="utf-8"))
        self.assertIn("2 attempt(s) thrown away, 1 topic(s) dropped (reasons: newspaper_names)", line)
        self.assertEqual(len(saved["attempts"]), 2)

    def test_summary_line_is_printed_even_when_nothing_was_rejected_and_no_file_is_written(self):
        sb.BIWEEKLY_REJECTED.clear()
        with tempfile.TemporaryDirectory() as d, mock.patch.object(sb, "REVIEW_FLAGS_DIR", Path(d)):
            line = sb.write_rejected_report("2026-11-18")
            self.assertEqual(list(Path(d).iterdir()), [])
        self.assertEqual(line, "Biweekly rejected text: 0 attempt(s) thrown away, 0 topic(s) dropped")

    def test_rejected_text_goes_to_its_own_file_not_into_the_events(self):
        topic = {"topic_label_en": "T", "article_ids": [1]}
        comparison = {"topic_label_de": "x", "comparison_text_he": "טקסט עם נתניהu", "comparison_text_en": "e", "comparison_text_de": "d"}
        synthesize.STAGE2_EVENT_LOG.clear()
        synthesize.STAGE2_REJECTED_LOG.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            synthesize._log_stage2_failure(topic, "mixed_script", 1, detail="x", comparison=comparison)
        self.assertNotIn("rejected", synthesize.STAGE2_EVENT_LOG[0])  # stage2_events.json is tracked in git: format unchanged
        self.assertEqual(synthesize.STAGE2_REJECTED_LOG[0]["rejected"]["comparison_text_he"], "טקסט עם נתניהu")
        block = "\n".join(synthesize.format_stage2_events_block(synthesize.STAGE2_EVENT_LOG))
        self.assertNotIn("נתניהu", block)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(synthesize, "PROJECT_ROOT", Path(d)):
            synthesize.write_stage2_events("2026-11-18", synthesize.STAGE2_EVENT_LOG)
            flags = Path(d) / "data" / "processed" / "review_flags"
            events = json.loads((flags / "2026-11-18.stage2_events.json").read_text(encoding="utf-8"))
            self.assertNotIn("נתניהu", json.dumps(events, ensure_ascii=False))
            rej = json.loads((flags / "2026-11-18.stage2_rejected.json").read_text(encoding="utf-8"))
            self.assertIn("נתניהu", json.dumps(rej, ensure_ascii=False))
        synthesize.STAGE2_EVENT_LOG.clear()
        synthesize.STAGE2_REJECTED_LOG.clear()


class CheckpointTest(unittest.TestCase):
    PERIOD = ("2026-11-05", "2026-11-18")
    DAYS = [{"id": 1, "report_date": "2026-11-05", "topic_label_en": "a", "comparison_text_en": "text one"}]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(sb, "CHECKPOINT_DIR", Path(self.tmp.name))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_a_finished_topic_is_reused_by_the_next_run_without_an_api_call(self):
        calls = []

        def fake(client, topic, days, feedback=""):
            calls.append(1)
            return dict(result()), {"input_tokens": 1, "output_tokens": 1}

        with mock.patch.object(sb, "write_biweekly_topic", side_effect=fake), contextlib.redirect_stdout(io.StringIO()) as out:
            first = sb.write_topic_checkpointed(None, TOPIC, self.DAYS, self.PERIOD)
            second = sb.write_topic_checkpointed(None, TOPIC, self.DAYS, self.PERIOD)
        self.assertEqual(len(calls), 1)
        self.assertEqual(first[0], second[0])
        self.assertIn("reusing checkpoint", out.getvalue())
        self.assertEqual(second[1]["output_tokens"], 0)

    def test_a_dropped_topic_is_not_checkpointed_so_a_rerun_tries_it_again(self):
        with mock.patch.object(sb, "write_biweekly_topic", return_value=({"comparison_text_he": "0", "comparison_text_en": "0",
                                                                          "comparison_text_de": "0", "topic_label_he": "x"}, {})), \
             contextlib.redirect_stdout(io.StringIO()):
            res = sb.write_topic_checkpointed(None, TOPIC, self.DAYS, self.PERIOD)
        self.assertIsNone(res[0])
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_changing_the_prompt_or_the_topic_input_makes_the_checkpoint_invisible(self):
        with mock.patch.object(sb, "write_biweekly_topic", return_value=(dict(result()), {"input_tokens": 1, "output_tokens": 1})) as w, \
             contextlib.redirect_stdout(io.StringIO()):
            sb.write_topic_checkpointed(None, TOPIC, self.DAYS, self.PERIOD)
            with mock.patch.object(sb, "BIWEEKLY_STAGE2_SYSTEM_PROMPT", sb.BIWEEKLY_STAGE2_SYSTEM_PROMPT + " changed"):
                sb.write_topic_checkpointed(None, TOPIC, self.DAYS, self.PERIOD)
            sb.write_topic_checkpointed(None, TOPIC, [dict(self.DAYS[0], comparison_text_en="other text")], self.PERIOD)
        self.assertEqual(w.call_count, 3)

    def test_without_a_period_nothing_is_checkpointed(self):
        with mock.patch.object(sb, "write_biweekly_topic", return_value=(dict(result()), {"input_tokens": 1, "output_tokens": 1})), \
             contextlib.redirect_stdout(io.StringIO()):
            sb.write_topic_checkpointed(None, TOPIC, self.DAYS, None)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_the_end_of_run_cleanup_removes_the_topic_checkpoints_too(self):
        with mock.patch.object(sb, "write_biweekly_topic", return_value=(dict(result()), {"input_tokens": 1, "output_tokens": 1})), \
             contextlib.redirect_stdout(io.StringIO()):
            sb.write_topic_checkpointed(None, TOPIC, self.DAYS, self.PERIOD)
        self.assertEqual(sb.clear_checkpoints(*self.PERIOD), 1)


if __name__ == "__main__":
    unittest.main()
