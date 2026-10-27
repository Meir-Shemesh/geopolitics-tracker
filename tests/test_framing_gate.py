"""Tests for the opening-sentence framing gate in synthesize.py (PROJECT_LOG 4.112).

The gate fires only when (a) the opening sentence divides the coverage by country/language in any of the three texts AND
(b) some country is represented by two or more of the topic's newspapers. Sections 4990, 4649 and 4879 are the real
2026-10-24/26 cases; their opening sentences below are copied from the published reports.
"""

import unittest
from unittest import mock

from src.reporting import synthesize as syn

S4990 = {  # Telegraph vs Guardian are both British: the published opening contradicted the body
    "comparison_text_he": "הסיקור של האירוע מתחלק בבירור בין הדיווח הבריטי לדיווח הגרמני-שוויצרי. The Daily Telegraph מציג...",
    "comparison_text_en": "Coverage splits clearly between the British and the German-language press. The Daily Telegraph, in...",
    "comparison_text_de": "Die Berichterstattung fällt deutlich zwischen der britischen und der deutschsprachigen Presse auseinander. The Daily...",
}
N4990 = ["Frankfurter Allgemeine Zeitung", "Neue Zürcher Zeitung", "Daily Telegraph", "Guardian"]

S4649 = {  # Welt + Süddeutsche (both German) and Telegraph + NZZ
    "comparison_text_he": "הסיקור מתפצל לשני זירות לאומיות ולזוויות שונות בתוכן. The Daily Telegraph...",
    "comparison_text_en": "Coverage splits along national lines and differs sharply in angle. The Daily Telegraph...",
    "comparison_text_de": "Die Berichterstattung teilt sich klar nach Ländern und Blickwinkeln auf. The Daily Telegraph...",
}
N4649 = ["Süddeutsche Zeitung", "Neue Zürcher Zeitung", "Die Welt", "Daily Telegraph"]

S4879 = {  # one newspaper per country: a national framing is legitimate and must not trigger the gate
    "comparison_text_he": "הנושא מקבל שתי זוויות עיקריות, קנדית ואירופית, שלא תמיד חופפות זו לזו. The Globe and Mail...",
    "comparison_text_en": "Coverage of this topic splits along national lines, Canadian and European, and even within each country's own press there is tension between pieces.",
    "comparison_text_de": "Die Berichterstattung zu diesem Thema verläuft entlang nationaler Linien, kanadisch und europäisch, wobei selbst innerhalb der jeweiligen Presse Spannungen bestehen.",
}
N4879 = ["Globe and Mail", "Neue Zürcher Zeitung"]


def comparison(he="", en="", de=""):
    return {"comparison_text_he": he, "comparison_text_en": en, "comparison_text_de": de}


class GateDecisionTest(unittest.TestCase):
    def test_4990_fires_in_all_three_languages(self):
        conflict = syn.national_framing_conflict(S4990, N4990)
        self.assertEqual(conflict["languages"], ["he", "en", "de"])
        self.assertEqual(conflict["groups"], {"UK": ["The Daily Telegraph", "The Guardian"]})

    def test_4649_fires(self):
        conflict = syn.national_framing_conflict(S4649, N4649)
        self.assertEqual(set(conflict["languages"]), {"he", "en", "de"})
        self.assertIn("Germany", conflict["groups"])

    def test_4879_does_not_fire_one_newspaper_per_country(self):
        self.assertIsNone(syn.national_framing_conflict(S4879, N4879))

    def test_a_national_opening_is_not_a_conflict_when_no_country_has_two_papers(self):
        self.assertIsNone(syn.national_framing_conflict(S4990, ["Daily Telegraph", "Neue Zürcher Zeitung", "Wall Street Journal"]))

    def test_the_economist_never_forms_a_same_country_group(self):
        self.assertEqual(syn.same_country_groups(["Economist", "Guardian"]), {})

    def test_a_stance_based_opening_does_not_fire_even_with_same_country_papers(self):
        stance = comparison(
            "הסיקור של האירוע מתחלק בבירור בין הצגת המבצע כמענה ביטחוני לבין תיאורו כעונש קולקטיבי.",
            "Coverage splits clearly between presenting the operation as a security response and describing it as collective punishment.",
            "Die Berichterstattung teilt sich deutlich in eine Darstellung als Sicherheitsmaßnahme und eine Lesart als kollektive Bestrafung.",
        )
        self.assertIsNone(syn.national_framing_conflict(stance, N4990))

    def test_a_negated_national_mention_does_not_fire(self):
        near_miss = comparison(
            "הסיקור מתחלק פחות לפי קווים לאומיים ויותר סביב השאלה מי אחראי.",
            "Coverage splits less along national lines than over where the real danger lies.",
            "Die Berichterstattung teilt sich weniger entlang nationaler Linien als darüber, wo die eigentliche Gefahr liegt.",
        )
        self.assertIsNone(syn.national_framing_conflict(near_miss, N4990))

    def test_international_is_not_a_national_framing(self):
        self.assertFalse(syn.frames_by_nationality("Coverage of the international response splits over sanctions.", "en"))
        self.assertFalse(syn.frames_by_nationality("התגובה הבינלאומית מתחלקת בשאלת הסנקציות.", "he"))
        self.assertFalse(syn.frames_by_nationality("Die internationale Reaktion spaltet sich bei den Sanktionen.", "de"))

    def test_a_national_split_is_recognised_and_a_stance_split_is_not(self):
        self.assertTrue(syn.frames_by_nationality("Coverage splits sharply between American outlets and European outlets.", "en"))
        self.assertFalse(syn.frames_by_nationality("Coverage splits sharply over whether sanctions can work at all.", "en"))

    def test_hebrew_false_friends_do_not_fire(self):
        # "כלפי מדיניות" contains "לפי מדינ"; "הזירה הלאומית" is the domestic arena, not a national split
        self.assertFalse(syn.frames_by_nationality("שתי כתבות מציגות זווית ביקורתית כלפי מדיניות ההגירה של ממשל טראמפ, אך בדגשים שונים.", "he"))
        self.assertFalse(syn.frames_by_nationality("הכיסוי מתמקד בזירה הלאומית ובזיקה בין מדיניות החוץ לכלכלת הבוחרים, אך בדגשים שונים.", "he"))
        self.assertFalse(syn.frames_by_nationality("הסיקור מתחלק בשאלת הביטחון הלאומי ובמחיר הכלכלי.", "he"))

    def test_topic_countries_are_not_press_origins(self):
        # the US-Canada friction is the subject matter, not a statement about which press says what
        self.assertFalse(syn.frames_by_nationality("The three outlets approach the US-Canada friction from markedly different angles.", "en"))
        self.assertFalse(syn.frames_by_nationality("Both German outlets cover Canada's outreach to the EU, but with different degrees of engagement.", "en"))

    def test_corrected_4990_opening_does_not_fire(self):
        fixed = comparison(
            "הסיקור של האירוע מתחלק בבירור בין הצגת המבצע כמענה ביטחוני, על פי הגרסה הישראלית הרשמית, לבין תיאורו כעונש קולקטיבי וכגירוש הקשורים לפוליטיקת הבחירות בישראל, כשביניהם עומד דיווח מאוזן יותר.",
            "Coverage splits clearly between presenting the operation as a security response, in line with Israel's official account, and describing it as collective punishment and displacement tied to Israeli election politics, with a more measured report in between.",
            "Die Berichterstattung teilt sich deutlich zwischen der Darstellung der Operation als Sicherheitsmaßnahme nach der offiziellen israelischen Lesart und ihrer Beschreibung als kollektive Bestrafung und Vertreibung im Zusammenhang mit der israelischen Wahlkampfpolitik; dazwischen steht eine nüchternere Berichterstattung.",
        )
        self.assertIsNone(syn.national_framing_conflict(fixed, N4990))

    def test_us_abbreviation_does_not_cut_the_opening_sentence_short(self):
        self.assertTrue(syn.frames_by_nationality("Coverage splits between U.S. outlets and German outlets. Details follow.", "en"))


class RetryTest(unittest.TestCase):
    TOPIC = {"topic_label_en": "Hebron", "topic_label_he": "חברון"}
    ARTICLES = [{"newspaper": n} for n in N4990]
    GOOD = comparison(
        "הסיקור מתחלק בין הצגת המבצע כמענה ביטחוני לבין תיאורו כעונש קולקטיבי וגירוש של אוכלוסייה אזרחית.",
        "Coverage splits between presenting the operation as a security response and describing it as collective punishment and displacement.",
        "Die Berichterstattung teilt sich zwischen der Darstellung als Sicherheitsmaßnahme und der Lesart als kollektive Bestrafung und Vertreibung.",
    )

    def run_retry(self, first, second=None, raises=False):
        calls = []

        def fake(client, topic, arts, feedback=None):
            calls.append(feedback)
            if raises:
                raise RuntimeError("boom")
            return {"input_tokens": 1}, dict(second)

        with mock.patch.object(syn, "write_topic_comparison", side_effect=fake):
            result = syn._retry_for_national_framing(None, self.TOPIC, self.ARTICLES, {"input_tokens": 0}, dict(first))
        return result, calls

    def test_conflict_triggers_exactly_one_rewrite_with_named_pairs_and_the_rewrite_is_used(self):
        (usage, comp), calls = self.run_retry(S4990, self.GOOD)
        self.assertEqual(len(calls), 1)
        self.assertIn("The Daily Telegraph and The Guardian", calls[0])
        self.assertEqual(comp["comparison_text_en"], self.GOOD["comparison_text_en"])

    def test_no_conflict_means_no_extra_call(self):
        (usage, comp), calls = self.run_retry(self.GOOD, self.GOOD)
        self.assertEqual(calls, [])
        self.assertEqual(comp, self.GOOD)

    def test_failed_rewrite_keeps_the_original(self):
        (usage, comp), calls = self.run_retry(S4990, None, raises=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(comp["comparison_text_en"], S4990["comparison_text_en"])

    def test_still_national_after_the_rewrite_is_kept_not_looped_and_flagged_by_audit(self):
        (usage, comp), calls = self.run_retry(S4990, S4649)
        self.assertEqual(len(calls), 1)  # one retry only
        sections = [{"topic_label_en": "x", "article_ids": [1, 2, 3, 4], **comp}]
        articles = [{"id": i + 1, "newspaper": n} for i, n in enumerate(N4990)]
        flags = syn.audit_sections(sections, articles)
        self.assertTrue(any("OPENING DIVIDES BY COUNTRY/LANGUAGE" in f for f in flags))

    def test_audit_is_silent_for_a_stance_based_opening(self):
        sections = [{"topic_label_en": "x", "article_ids": [1, 2, 3, 4], **self.GOOD}]
        articles = [{"id": i + 1, "newspaper": n} for i, n in enumerate(N4990)]
        self.assertEqual([f for f in syn.audit_sections(sections, articles) if "OPENING DIVIDES" in f], [])


if __name__ == "__main__":
    unittest.main()
