"""Stage 2 per-topic failure logging (PROJECT_LOG 4.141): log lines only, retry/fallback handling unchanged."""

import contextlib
import io
import unittest
from unittest import mock

from src.reporting import synthesize

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
