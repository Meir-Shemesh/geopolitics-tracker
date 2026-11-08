"""Tests for the newspaper-nationality prompt rule and audit flag in synthesize.py (PROJECT_LOG 4.131).

Section 6139 (2026-11-07) called The Guardian, Los Angeles Times and The Washington Post "all three major American
papers" in all three languages; 2719 (he) and 4870 (he/en/de) are the two older real cases. The text below is copied
from the published reports. Contrasts ("the German paper ... the Telegraph") must NOT be flagged.
"""

import unittest

from src.reporting import synthesize as syn

EN_6139 = "All three major American papers covering this event - The Guardian, the Los Angeles Times and The Washington Post - agree that"
HE_6139 = "כל שלושת העיתונים האמריקאיים המרכזיים - The Guardian, Los Angeles Times ו-The Washington Post - מסכימים ש"
DE_6139 = "Die drei großen amerikanischen Zeitungen, die über dieses Ereignis berichten - The Guardian, Los Angeles Times und The Washington Post - sind sich einig"
HE_2719 = "בעוד שני עיתונים גרמניים - Süddeutsche Zeitung ו-Washington Post במאמרים נפרדים על בינה מלאכותית - מציינים"
EN_4870 = "sharply critical framing in the American outlets, especially the Los Angeles Times and Süddeutsche Zeitung."
DE_4870 = "bis zu scharf kritischer Einordnung in den amerikanischen Medien, besonders bei der Los Angeles Times und der Süddeutschen Zeitung."
HE_4870 = "לביקורת פוליטית חריפה בעיתונות האמריקאית, במיוחד ב-Los Angeles Times וב-Süddeutsche Zeitung."


class NationalityAuditTest(unittest.TestCase):
    def wrong_names(self, text, lang):
        return [n for hit in syn.newspaper_nationality_conflicts(text, lang) for n, _ in hit["wrong"]]

    def test_6139_flagged_in_all_three_languages(self):
        for text, lang in ((EN_6139, "en"), (HE_6139, "he"), (DE_6139, "de")):
            self.assertEqual(self.wrong_names(text, lang)[0].replace("The ", ""), "Guardian", lang)

    def test_other_real_cases(self):
        self.assertEqual(self.wrong_names(HE_2719, "he"), ["Washington Post"])
        self.assertEqual(self.wrong_names(EN_4870, "en"), ["Süddeutsche Zeitung"])
        self.assertEqual(self.wrong_names(DE_4870, "de"), ["Süddeutschen Zeitung"])
        self.assertEqual(self.wrong_names(HE_4870, "he"), ["Süddeutsche Zeitung"])

    def test_correct_labels_pass(self):
        self.assertEqual(self.wrong_names("The American papers - Los Angeles Times and The Washington Post - agree", "en"), [])
        self.assertEqual(self.wrong_names("both British papers, especially The Guardian and The Daily Telegraph", "en"), [])
        self.assertEqual(self.wrong_names("the German-language press - Die Welt and Neue Zürcher Zeitung - differ", "en"), [])
        self.assertEqual(self.wrong_names("עיתונים בריטיים - The Guardian ו-The Daily Telegraph - חלוקים", "he"), [])

    def test_economist_is_international(self):
        self.assertEqual(self.wrong_names("the British papers - The Guardian and The Economist - agree", "en"), [])

    def test_contrast_is_not_flagged(self):
        # legitimate: a nationality label followed by a clause, then another paper in a contrast
        self.assertEqual(self.wrong_names("Where the German paper frames it as a crisis, the Telegraph presents it as a power struggle.", "en"), [])
        self.assertEqual(self.wrong_names("בעוד העיתונים הגרמניים בוחנים את הדינמיקה הפוליטית והמוסדית, The Globe and Mail ו-USA Today מדגישים", "he"), [])
        self.assertEqual(self.wrong_names("שני עיתונים בריטים ו-The Washington Post מתמודדים עם אותה הצהרה", "he"), [])

    def test_sueddeutsche_is_not_a_german_label(self):
        self.assertEqual(self.wrong_names("Die Süddeutsche Zeitung und The Guardian berichten", "de"), [])

    def test_audit_sections_reports_it(self):
        sec = {"topic_label_en": "T", "comparison_text_he": HE_6139, "comparison_text_en": EN_6139, "comparison_text_de": DE_6139,
               "article_ids": []}
        flags = [f for f in syn.audit_sections([sec], []) if f.startswith("NEWSPAPER NATIONALITY")]
        self.assertEqual(len(flags), 3)


class PromptTest(unittest.TestCase):
    def test_prompt_carries_the_country_list_and_the_rule(self):
        p = syn.STAGE2_SYSTEM_PROMPT
        self.assertIn("The Guardian = UK", p)
        self.assertIn("The Washington Post = US", p)
        self.assertIn("Neue Zürcher Zeitung = Switzerland", p)
        self.assertIn("Guardian US desk", p)

    def test_list_is_built_from_the_canonical_mapping(self):
        for key, country in syn.NEWSPAPER_COUNTRIES.items():
            if key in syn.NEWSPAPER_DISPLAY_NAMES:
                self.assertIn(f"{syn.NEWSPAPER_DISPLAY_NAMES[key]} = {country}", syn._NEWSPAPER_COUNTRY_LIST)


if __name__ == "__main__":
    unittest.main()
