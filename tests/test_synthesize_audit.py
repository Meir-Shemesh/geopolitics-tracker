"""Final-text audit in synthesize.py (PROJECT_LOG 4.102): foreign-script leaks, a digit 1
wedged between names, and prose newspaper counts that disagree with the cited sources.
No API, no tracker.db."""
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.reporting import synthesize as syn  # noqa: E402


class ForeignScriptTest(unittest.TestCase):
    def test_legitimate_text_is_clean(self):
        for text in (
            "בטור ב-The Daily Telegraph, רוג'ר ארתור כותב: “לא” – ו-Jackdaw 50% €3 → Süddeutsche Zeitung, Zürcher, Müller, café",
            "Der Spiegel berichtet über Bundeskanzler Merz – „Flughafen Riad“",
            "Brexit-1 would be wrong, but 12-13 October is fine",
        ):
            self.assertEqual(syn.foreign_script_chars(text), [], text)

    def test_the_three_real_leaks_of_2026_10_18_19_are_caught(self):
        cyrillic = "קווין לайлס טוען"
        arabic = "פרנקפורטר אלגماينה צייטונג"
        telugu = "טראמప והרפובליקנים"
        self.assertEqual({hex(ord(c)) for c in syn.foreign_script_chars(cyrillic)}, {"0x430", "0x439", "0x43b"})
        self.assertTrue(syn.foreign_script_chars(arabic))
        self.assertEqual([hex(ord(c)) for c in syn.foreign_script_chars(telugu)], ["0xc2a"])


class AuditTest(unittest.TestCase):
    ARTICLES = [
        {"id": 1, "newspaper": "Los Angeles Times"}, {"id": 2, "newspaper": "Los Angeles Times"},
        {"id": 3, "newspaper": "Washington Post"}, {"id": 4, "newspaper": "USA Today"},
    ]

    def section(self, **kw):
        base = {"topic_label_he": "נושא", "topic_label_en": "Topic", "topic_label_de": "Thema",
                "comparison_text_he": "טקסט תקין", "comparison_text_en": "ok text", "comparison_text_de": "Text",
                "article_ids": [1, 2, 3, 4]}
        base.update(kw)
        return base

    def test_four_articles_from_three_papers_flags_a_claim_of_four(self):
        flags = syn.audit_sections([self.section(comparison_text_he="ארבעה עיתונים אמריקאיים בוחנים")], self.ARTICLES)
        self.assertEqual(len(flags), 1)
        self.assertIn("says 4 newspapers", flags[0])
        self.assertIn("from 3", flags[0])

    def test_correct_or_smaller_claims_are_not_flagged(self):
        for text in ("שלושה עיתונים אמריקאיים בוחנים", "שני עיתונים מדווחים"):
            self.assertEqual(syn.audit_sections([self.section(comparison_text_he=text)], self.ARTICLES), [], text)

    def test_english_and_german_claims(self):
        flags = syn.audit_sections([self.section(comparison_text_en="Four American newspapers examine",
                                                 comparison_text_de="Vier Zeitungen berichten")], self.ARTICLES)
        self.assertEqual(len(flags), 2)

    def test_outlets_and_medien_wordings_are_counted_too(self):
        # found by hand in the 2026-09-04/05/21 sections: "Five outlets", "Die fünf Medien"
        flags = syn.audit_sections([self.section(comparison_text_en="Five outlets weigh the pressure",
                                                 comparison_text_de="Die fünf Medien nähern sich")], self.ARTICLES)
        self.assertEqual(len(flags), 2)

    def test_external_fact_with_a_large_number_is_not_flagged(self):
        # 2026-10-10: "placed in roughly 100 articles across about 20 news outlets" (a disinformation campaign)
        flags = syn.audit_sections([self.section(comparison_text_en="placed in articles across about 20 news outlets")],
                                   self.ARTICLES)
        self.assertEqual(flags, [])

    def test_label_leak_is_reported_even_though_the_retry_gate_cannot_reask_it(self):
        flags = syn.audit_sections([self.section(topic_label_he="תקיפה בשדה लन")], self.ARTICLES)
        self.assertEqual(len(flags), 1)
        self.assertIn("topic_label_he", flags[0])

    def test_digit_one_between_names_is_flagged_but_vav_and_numbers_are_not(self):
        for bad in ("Globe and Mail-1 Los Angeles Times", "Rosebank 1-Jackdaw", "Benedict Smith 1-Poppy Wood"):
            self.assertTrue(syn.audit_sections([self.section(comparison_text_he=bad)], self.ARTICLES), bad)
        for ok in ("Globe and Mail ו-Los Angeles Times", "Rosebank ו-Jackdaw", "בין 1-2 באוקטובר", "ה-12-13 באוקטובר",
                   "מפציצי ה-B-1 האמריקאיים מבסיס RAF Fairford", "נוסעים מאז ב-1 באוגוסט"):
            self.assertEqual(syn.audit_sections([self.section(comparison_text_he=ok)], self.ARTICLES), [], ok)


class RetryGateTest(unittest.TestCase):
    def comparison(self, he):
        return {"topic_label_de": "Thema", "comparison_text_he": he,
                "comparison_text_en": "x" * 80, "comparison_text_de": "y" * 80}

    def test_script_leak_triggers_the_retry_and_a_clean_retry_is_accepted(self):
        topic = {"topic_label_en": "t"}
        leaky = self.comparison("א" * 60 + "а")
        clean = self.comparison("א" * 60)
        with mock.patch.object(syn, "write_topic_comparison", side_effect=[({}, leaky), ({}, clean)]) as w:
            out = syn.write_topic_comparison_with_retry(None, topic, [])
        self.assertEqual(w.call_count, 2)
        self.assertEqual(out[1]["comparison_text_he"], "א" * 60)

    def test_two_leaky_attempts_fall_back_to_per_article_sections(self):
        leaky = self.comparison("א" * 60 + "а")
        with mock.patch.object(syn, "write_topic_comparison", side_effect=[({}, leaky), ({}, leaky)]):
            self.assertIsNone(syn.write_topic_comparison_with_retry(None, {"topic_label_en": "t"}, []))


if __name__ == "__main__":
    unittest.main()
