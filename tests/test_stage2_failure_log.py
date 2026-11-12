"""Stage 2 per-topic failure logging (PROJECT_LOG 4.141): log lines only, retry/fallback handling unchanged."""

import contextlib
import io
import unittest
from unittest import mock

from src.reporting import synthesize
import src.reporting.synthesize_biweekly  # noqa: F401  (lazy import inside the name check reconfigures stdout; do it before redirect_stdout)

GOOD = {
    "topic_label_de": "Thema",
    "comparison_text_he": "השוואה בעברית שהיא מספיק ארוכה כדי לא להיחשב חשודה בשום צורה.",
    "comparison_text_en": "A comparison in English that is long enough not to look suspicious in any way at all.",
    "comparison_text_de": "Ein Vergleich auf Deutsch, der lang genug ist, um in keiner Weise verdächtig zu wirken.",
}
ARABIC_HE = dict(GOOD, comparison_text_he="מים לטקס הוضوء במסגד, ואחר כך עוד טקסט עברי ארוך מספיק כדי לעבור.")
TOPIC = {"topic_label_en": "Water scarcity in Jordan", "article_ids": [14617]}
ARTICLES = [{"newspaper": "Guardian", "id": 14617}]


def run(side_effects):
    out = io.StringIO()
    with mock.patch.object(synthesize, "write_topic_comparison", side_effect=side_effects), \
         contextlib.redirect_stdout(out):
        result = synthesize.write_topic_comparison_with_retry(None, TOPIC, ARTICLES)
    return result, out.getvalue()


class StageTwoFailureLog(unittest.TestCase):
    def test_arabic_twice_logs_each_attempt_and_final_failure_and_still_returns_none(self):
        result, log = run([({}, ARABIC_HE), ({}, ARABIC_HE)])
        self.assertIsNone(result)  # handling unchanged: falls back
        lines = [l for l in log.splitlines() if "STAGE2" in l]
        self.assertEqual(len(lines), 2)
        self.assertIn("reason=foreign_script_chars", lines[0])
        self.assertIn("attempt=1", lines[0])
        self.assertIn("STAGE2 FAILED_TOPIC", lines[1])
        for l in lines:
            self.assertIn("Water scarcity in Jordan", l)
            self.assertIn("article_ids=[14617]", l)
            self.assertIn("U+0636", l)  # Arabic dad
        self.assertIn("per-article fallback", lines[1])

    def test_error_twice_logs_error_reason(self):
        result, log = run([RuntimeError("boom"), RuntimeError("boom")])
        self.assertIsNone(result)
        self.assertEqual(log.count("reason=error"), 3)  # two attempts + final
        self.assertIn("FAILED_TOPIC", log)

    def test_clean_answer_logs_nothing(self):
        with mock.patch.object(synthesize, "_retry_for_national_framing", side_effect=lambda c, t, a, u, comp: (u, comp)), \
             mock.patch.object(synthesize, "_retry_for_hebrew_newspaper_names", side_effect=lambda c, t, a, u, comp: (u, comp)):
            result, log = run([({}, GOOD)])
        self.assertIsNotNone(result)
        self.assertNotIn("STAGE2", log)

    def test_logging_never_raises(self):
        with mock.patch.object(synthesize, "format_stage2_failure_line", side_effect=ValueError("x")):
            synthesize._log_stage2_failure(TOPIC, "error")  # must not raise


if __name__ == "__main__":
    unittest.main()


class StageTwoEventsRecord(unittest.TestCase):
    """PROJECT_LOG 4.143: events survive the 40-line log tail via an end-of-run block and a JSON file."""

    TELL_HE = dict(GOOD, comparison_text_he="העיתון טלגרף מדווח כי הממשלה הבריטית החליטה על צעד חדש ומרחיק לכת בנושא.")

    def setUp(self):
        synthesize.STAGE2_EVENTS.clear()
        synthesize.STAGE2_EVENT_LOG.clear()
        synthesize.STAGE2_RUN_INFO.clear()
        synthesize.STAGE2_RUN_INFO.update(topics=1, batch_enabled=False, answered=0, wait_seconds=0.0)

    def _retry_once(self):
        out = io.StringIO()
        with mock.patch.object(synthesize, "write_topic_comparison", side_effect=[({}, GOOD)]), \
             mock.patch.object(synthesize, "_retry_for_national_framing", side_effect=lambda c, t, a, u, comp: (u, comp)), \
             contextlib.redirect_stdout(out):
            result = synthesize.write_topic_comparison_with_retry(None, TOPIC, ARTICLES, first=({}, self.TELL_HE))
        return result, out.getvalue()

    def test_hebrew_names_retry_is_recorded_with_outcome_and_handling_unchanged(self):
        result, _ = self._retry_once()
        self.assertEqual(result[1], GOOD)  # the retry's answer is used, as before
        self.assertEqual(synthesize.STAGE2_EVENTS["hebrew_names"], 1)
        events = synthesize.STAGE2_EVENT_LOG
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "hebrew_names")
        self.assertEqual(events[0]["article_ids"], [14617])
        self.assertEqual(events[0]["outcome"], "resolved_by_retry")

    def test_event_appears_in_file_and_in_block_right_before_summary(self):
        import json, tempfile, pathlib
        self._retry_once()
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with mock.patch.object(synthesize, "PROJECT_ROOT", pathlib.Path(tmp)), \
                 mock.patch.object(synthesize, "summarize_api_usage", return_value={"cost": 0.5}), \
                 contextlib.redirect_stdout(out):
                synthesize.print_stage2_summary("2026-11-13", "2026-11-13")
            data = json.loads((pathlib.Path(tmp) / "data/processed/review_flags/2026-11-13.stage2_events.json")
                              .read_text(encoding="utf-8"))
        self.assertEqual(data["events"][0]["kind"], "hebrew_names")
        self.assertEqual(data["events"][0]["outcome"], "resolved_by_retry")
        lines = out.getvalue().splitlines()
        self.assertTrue(lines[-1].startswith("Stage 2 summary"))
        self.assertIn("hebrew_names", lines[-2])
        self.assertIn("outcome=resolved_by_retry", lines[-2])
        self.assertTrue(lines[-3].startswith("Stage 2 events (1)"))

    def test_fallback_outcome_and_block_cap(self):
        run([({}, ARABIC_HE), ({}, ARABIC_HE)])
        self.assertEqual({e["outcome"] for e in synthesize.STAGE2_EVENT_LOG}, {"fell_to_fallback"})
        many = [{"topic": f"t{i}", "article_ids": [i], "kind": "error", "attempt": 1, "detail": "",
                 "foreign_chars": {}, "final": False, "outcome": "resolved_by_retry"} for i in range(25)]
        block = synthesize.format_stage2_events_block(many)
        self.assertEqual(len(block), 1 + synthesize.STAGE2_EVENTS_BLOCK_MAX_LINES + 1)
        self.assertIn("15 more", block[-1])
        self.assertEqual(synthesize.format_stage2_events_block([]), [])
