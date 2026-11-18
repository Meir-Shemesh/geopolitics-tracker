"""The shared text checks of the daily and the biweekly writer (src/reporting/text_checks.py), tested on REAL snippets from
the published archive exported by the 2026-11-15 offline audit (tests/fixtures/text_checks_real_cases.json): the 18 words
with Latin letters fused into Hebrew, the 32 glued Hebrew prefixes, the Hebrew-letter newspaper names that leaked, the
legitimate uses that must NOT be caught (Times Square, Janet Daily, Hubert Spiegel, Los Angeles the city), the Tamil letter
and the two sections whose Hebrew field contained markup. Plus the retry wiring of both writers, with mocked API calls."""

import contextlib
import io
import json
import os
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")

from src.reporting import synthesize, synthesize_biweekly as sb
from src.reporting import text_checks as tc

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "text_checks_real_cases.json").read_text(encoding="utf-8"))


class RealCasesTest(unittest.TestCase):
    def test_all_18_words_with_latin_letters_inside_hebrew_are_caught(self):
        self.assertEqual(len(FIXTURE["splice"]), 18)
        for case in FIXTURE["splice"]:
            words = tc.mixed_script_words(case["context"])
            self.assertIn(case["token"], words, case)

    def test_glued_hebrew_prefix_is_not_a_retry_trigger_but_is_repaired_with_a_hyphen(self):
        self.assertEqual(len(FIXTURE["prefix"]), 32)
        for case in FIXTURE["prefix"]:
            self.assertEqual(tc.mixed_script_words(case["context"]), [], case)
            fixed, n = tc.fix_attached_prefixes(case["context"])
            self.assertGreaterEqual(n, 1, case)
            token = case["token"]  # e.g. "הLos", "בSüddeutsche": prefix letters + the name's first word
            self.assertNotIn(token, fixed, case)
            self.assertIn(token[:1] + "-" + token[1:], fixed.replace("  ", " "), case) if len(token) > 2 and token[1] in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" else None
            self.assertEqual(tc.fix_attached_prefixes(fixed)[1], 0, "the repair is idempotent")

    def test_missing_space_after_a_latin_word_is_caught(self):
        for case in FIXTURE["missing_space"]:
            self.assertIn(case["token"], tc.mixed_script_words(case["context"]))

    def test_every_hebrew_letter_newspaper_name_that_leaked_is_caught(self):
        self.assertGreaterEqual(len(FIXTURE["name_leaks"]), 80)
        for case in FIXTURE["name_leaks"]:
            self.assertTrue(tc.hebrew_newspaper_name_tells(case["context"]), case)

    def test_legitimate_uses_are_not_caught(self):
        self.assertGreaterEqual(len(FIXTURE["name_legit"]), 50)
        for case in FIXTURE["name_legit"]:  # Times Square, Wall Street the street/market, Los Angeles the city, ...
            self.assertEqual(tc.hebrew_newspaper_name_tells(case["context"]), {}, case)

    def test_the_ambiguous_cases_are_decided_as_the_audit_recommended(self):
        by_id = {c["id"]: c for c in FIXTURE["name_ambiguous"]}
        self.assertTrue(tc.hebrew_newspaper_name_tells(by_id["1830"]["context"]))        # "הדיילי Daily Telegraph": a leak
        for ok in ("3252", "4945"):                                                        # Janet Daily
            self.assertEqual(tc.hebrew_newspaper_name_tells(by_id[ok]["context"]), {}, ok)
        self.assertEqual(tc.hebrew_newspaper_name_tells(by_id["4312"]["context"]), {})   # "הטיימס" alone: no longer a tell
        self.assertEqual(tc.hebrew_newspaper_name_tells(by_id["2301"]["context"]), {})   # "הפוסט" alone: not a tell

    def test_hubert_spiegel_and_times_square_stay_clean_but_the_magazine_is_caught(self):
        self.assertEqual(tc.hebrew_newspaper_name_tells("הוברט שפיגל נאם בכנס וטיימס סקוור התמלא"), {})
        self.assertIn("דר שפיגל", tc.hebrew_newspaper_name_tells("פרסום ב-דר שפיגל מגלה"))
        self.assertIn("השפיגל", tc.hebrew_newspaper_name_tells("לפי השפיגל הקואליציה נשברת"))
        self.assertIn("בשפיגל", tc.hebrew_newspaper_name_tells("בכתבה בשפיגל נטען"))
        self.assertIn("וול סטריט ג'", tc.hebrew_newspaper_name_tells("כתבה ב-וול סטריט ג'ורנל"))
        self.assertEqual(tc.hebrew_newspaper_name_tells("בועת המניות בוול סטריט והעיר לוס אנג'לס"), {})
        self.assertIn("לוס אנג'לס טיימס", tc.hebrew_newspaper_name_tells("מאמר ב-לוס אנג'לס טיימס"))

    def test_the_tamil_letter_that_was_published_is_caught_by_the_whitelist(self):
        self.assertEqual(len(FIXTURE["foreign_letters"]), 1)
        self.assertEqual(tc.foreign_script_chars(FIXTURE["foreign_letters"][0]["context"]), ["ப"])

    def test_markup_inside_the_hebrew_field_is_caught(self):
        caught = [c for c in FIXTURE["markup"] if c["id"] in ("1783", "1789")]
        self.assertEqual(len(caught), 2)
        for case in caught:
            self.assertTrue(tc.tag_fragments(case["context"]), case)


class UnitTest(unittest.TestCase):
    def test_hebrew_prefix_before_a_name_gets_a_hyphen_and_a_two_letter_word_gets_a_space(self):
        self.assertEqual(tc.fix_attached_prefixes("בSüddeutsche Zeitung"), ("ב-Süddeutsche Zeitung", 1))
        self.assertEqual(tc.fix_attached_prefixes("וה-Guardian והThe Daily"), ("וה-Guardian וה-The Daily", 1))
        self.assertEqual(tc.fix_attached_prefixes("מאת של Los Angeles")[1], 0)
        self.assertEqual(tc.fix_attached_prefixes("שלLos Angeles Times"), ("של Los Angeles Times", 1))
        self.assertEqual(tc.fix_attached_prefixes("ב-Süddeutsche וב-Die Welt"), ("ב-Süddeutsche וב-Die Welt", 0))

    def test_a_long_hebrew_word_before_a_capital_is_a_real_defect_not_a_prefix(self):
        self.assertTrue(tc.mixed_script_words("הממשלהThe"))
        self.assertTrue(tc.mixed_script_words("שלוש Süddeפ"))

    def test_clean_hebrew_with_latin_names_is_not_flagged(self):
        text = ("The Daily Telegraph ו-Frankfurter Allgemeine Zeitung מדווחים כי הממשלה בלונדון הגיבה ב-3-4 בנובמבר, "
                "ואילו Die Welt מתמקדת בהשלכות על הבורסה בוול סטריט (מדד S&P 500, ב-2028 ובעשור הבא).")
        self.assertEqual(tc.writer_problems({"comparison_text_he": text}, ("comparison_text_he",)), {})

    def test_mostly_non_hebrew_hebrew_field_is_flagged_but_short_and_normal_ones_are_not(self):
        english = "While all three articles address the drone dimension of the war, the coverage splits between sources " * 2
        self.assertEqual(tc.writer_problems({"comparison_text_he": english}, ("comparison_text_he",))["low_hebrew_ratio"]["comparison_text_he"], 0.0)
        self.assertIsNone(tc.hebrew_letter_ratio("The Guardian"))      # too few letters to judge
        self.assertIsNone(tc.low_hebrew_ratio("סיקור בעיתונים שונים של אותה פרשה, עם שמות כמו The Guardian ו-Die Welt בתוכו, ועוד קצת טקסט"))

    def test_tool_field_names_and_tags_are_markup(self):
        for bad in ("טקסט</comparison_text_he>", "<comparison_text_en>While", "overview_he: טקסט", "record_biweekly_topic", "</ant"):
            self.assertTrue(tc.tag_fragments(bad), bad)
        for ok in ("בין 1 ל-3 באוקטובר, מתחת ל-5% ומעל 2 > 1", "עלייה של 3% (מ-2 ל-3)"):
            self.assertEqual(tc.tag_fragments(ok), [], ok)

    def test_name_forms_are_only_counted(self):
        counts = tc.latin_name_form_counts("The Washington Post, Washington Post ו-Guardian, FAZ and the NZZ, The Guardian")
        self.assertEqual(counts, {"missing_the": 2, "abbreviations": 2})


class MergedTellListTest(unittest.TestCase):
    def test_the_requested_changes_to_the_list(self):
        t = tc.NEWSPAPER_NAME_TELLS
        for added in ("פרנקפורטר", "אלגמיינ", "צירכר", "ציריכר", "צוריכר", "גלוב אנד מייל", "אובזרבר", "אובסרבר", "גוארדיאן", "גרדיין",
                      "לוס אנג'לס טיימס", "וול סטריט ג'", "דר שפיגל", "השפיגל", "בשפיגל", "הדיילי"):
            self.assertIn(added, t, added)
        for removed in ("טיימס", "לוס אנג'לס", "וול סטריט", "שפיגל"):
            self.assertNotIn(removed, t, removed)

    def test_daily_and_biweekly_use_the_same_list(self):
        self.assertIs(sb.TRANSLITERATION_TELLS, tc.NEWSPAPER_NAME_TELLS)
        self.assertEqual(sb.hebrew_newspaper_violations("בגלוב אנד מייל"), synthesize.hebrew_newspaper_name_tells("בגלוב אנד מייל"))

    def test_a_newspaper_that_is_the_subject_of_the_story_still_counts(self):
        self.assertTrue(tc.hebrew_newspaper_name_tells("הצעת הרכישה של הטלגרף על ידי אקסל שפרינגר"))


class PromptTest(unittest.TestCase):
    def test_biweekly_prompt_lists_all_canonical_names(self):
        from src.reporting.render import NEWSPAPER_DISPLAY_NAMES
        self.assertEqual(len(NEWSPAPER_DISPLAY_NAMES), 15)
        for name in NEWSPAPER_DISPLAY_NAMES.values():
            self.assertIn(f'"{name}"', sb.BIWEEKLY_STAGE2_SYSTEM_PROMPT, name)
        self.assertIn("never \"הדיילי טלגרף\"", sb.BIWEEKLY_STAGE2_SYSTEM_PROMPT)

    def test_no_prompt_is_written_in_the_spaced_hyphen_style_and_each_forbids_it(self):
        for name, prompt in (("daily", synthesize.STAGE2_SYSTEM_PROMPT), ("biweekly", sb.BIWEEKLY_STAGE2_SYSTEM_PROMPT),
                             ("overview", sb.OVERVIEW_SYSTEM_PROMPT)):
            self.assertIn("do not use a spaced hyphen", prompt, name)
            # the only remaining spaced hyphens: the rule that names the style, and the quoted German house-style excerpt
            stripped = prompt.replace('(" - ")', "")
            self.assertLessEqual(stripped.count(" - "), 1, name)
        for tier, text in sb.DEPTH_INSTRUCTIONS.items():
            self.assertNotIn(" - ", text, tier)


def _good_daily():
    return {
        "topic_label_de": "Thema",
        "comparison_text_he": "השוואה בעברית שהיא מספיק ארוכה כדי לא להיחשב חשודה בשום צורה ומכילה גם The Guardian ו-Die Welt.",
        "comparison_text_en": "A comparison in English that is long enough not to look suspicious in any way at all.",
        "comparison_text_de": "Ein Vergleich auf Deutsch, der lang genug ist, um in keiner Weise verdächtig zu wirken.",
    }


class DailyRetryWiringTest(unittest.TestCase):
    TOPIC = {"topic_label_en": "Test topic", "article_ids": [1]}
    ARTICLES = [{"newspaper": "Guardian", "id": 1}]

    def run_topic(self, answers):
        calls = []

        def fake(client, topic, articles, feedback=None):
            calls.append(feedback)
            a = answers.pop(0)
            return {}, dict(a)

        out = io.StringIO()
        noop = lambda c, t, a, u, comp: (u, comp)
        with mock.patch.object(synthesize, "write_topic_comparison", side_effect=fake), \
             mock.patch.object(synthesize, "_retry_for_national_framing", side_effect=noop), \
             mock.patch.object(synthesize, "_retry_for_hebrew_newspaper_names", side_effect=noop), \
             contextlib.redirect_stdout(out):
            synthesize.STAGE2_LOG_ONLY.clear()
            result = synthesize.write_topic_comparison_with_retry(None, self.TOPIC, self.ARTICLES)
        return result, calls, out.getvalue()

    def test_a_word_with_latin_letters_inside_hebrew_triggers_one_retry_with_feedback_naming_the_word(self):
        bad = dict(_good_daily(), comparison_text_he=_good_daily()["comparison_text_he"] + " נתניהu אמר זאת.")
        result, calls, log = self.run_topic([bad, _good_daily()])
        self.assertIsNotNone(result)
        self.assertEqual(calls[0], None)
        self.assertIn("נתניהu", calls[1])
        self.assertIn("reason=mixed_script", log)

    def test_markup_in_the_hebrew_field_retries_and_a_second_failure_falls_back(self):
        bad = dict(_good_daily(), comparison_text_he=_good_daily()["comparison_text_he"] + "</comparison_text_he> <comparison_text_en>")
        result, calls, log = self.run_topic([bad, bad])
        self.assertIsNone(result)
        self.assertIn("reason=tag_fragment", log)
        self.assertIn("FAILED_TOPIC", log)

    def test_a_hebrew_field_in_english_retries(self):
        bad = dict(_good_daily(), comparison_text_he="While all three articles address the drone dimension of the war, the coverage splits between sources " * 2)
        result, calls, log = self.run_topic([bad, _good_daily()])
        self.assertIsNotNone(result)
        self.assertIn("reason=low_hebrew_ratio", log)

    def test_foreign_letters_in_english_or_german_text_retry_too(self):
        bad = dict(_good_daily(), comparison_text_en=_good_daily()["comparison_text_en"] + " ப")
        result, calls, log = self.run_topic([bad, _good_daily()])
        self.assertIsNotNone(result)
        self.assertIn("reason=foreign_script_chars", log)

    def test_a_glued_prefix_is_repaired_without_any_retry_and_is_counted(self):
        glued = dict(_good_daily(), comparison_text_he=_good_daily()["comparison_text_he"] + " בכתבה בSüddeutsche Zeitung נטען.")
        result, calls, log = self.run_topic([glued])
        self.assertIsNotNone(result)
        self.assertEqual(len(calls), 1)  # no retry
        self.assertIn("ב-Süddeutsche Zeitung", result[1]["comparison_text_he"])
        self.assertEqual(synthesize.STAGE2_LOG_ONLY["prefix_hyphen"], 1)

    def test_name_forms_without_the_are_counted_never_retried(self):
        text = dict(_good_daily(), comparison_text_en="Washington Post and the FAZ differ on the topic, which is long enough to be fine.")
        result, calls, log = self.run_topic([text])
        self.assertEqual(len(calls), 1)
        self.assertGreaterEqual(synthesize.STAGE2_LOG_ONLY["missing_the"], 1)
        self.assertGreaterEqual(synthesize.STAGE2_LOG_ONLY["abbreviations"], 1)

    def test_the_summary_prints_the_text_fix_line_before_the_summary_line(self):
        synthesize.STAGE2_LOG_ONLY.clear()
        synthesize.STAGE2_LOG_ONLY["prefix_hyphen"] = 2
        out = io.StringIO()
        with mock.patch.object(synthesize, "summarize_api_usage", return_value={"cost": 1.0}), contextlib.redirect_stdout(out):
            synthesize.print_stage2_summary("2026-11-16T00:00:00")
        lines = out.getvalue().splitlines()
        fix = next(i for i, l in enumerate(lines) if l.startswith("Stage 2 text fixes (no retry): prefix_hyphen=2"))
        summary = next(i for i, l in enumerate(lines) if l.startswith("Stage 2 summary:"))
        self.assertLess(fix, summary)


def _good_biweekly():
    return {
        "topic_label_he": "נושא", "topic_label_en": "Topic", "topic_label_de": "Thema",
        "comparison_text_he": "בתחילת התקופה The Guardian ו-Die Welt דיווחו בצורה זהירה, ובסופה הסיקור הפך חריף ומפורט הרבה יותר.",
        "comparison_text_en": "Early in the period The Guardian and Die Welt reported cautiously, and by the end the coverage grew sharper.",
        "comparison_text_de": "Zu Beginn berichteten The Guardian und Die Welt vorsichtig, am Ende wurde die Berichterstattung deutlich schärfer.",
    }


class BiweeklyRetryWiringTest(unittest.TestCase):
    TOPIC = {"topic_label_en": "Topic", "n_distinct_days": 6, "n_sources": 3}

    def run_topic(self, answers):
        feedbacks = []

        def fake(client, topic, days, feedback=""):
            feedbacks.append(feedback)
            return dict(answers.pop(0)), {"input_tokens": 1, "output_tokens": 1}

        out = io.StringIO()
        with mock.patch.object(sb, "write_biweekly_topic", side_effect=fake), contextlib.redirect_stdout(out):
            for k in sb.BIWEEKLY_LOG_ONLY:
                sb.BIWEEKLY_LOG_ONLY[k] = 0
            result = sb.write_biweekly_topic_with_retry(None, self.TOPIC, [])
        return result, feedbacks, out.getvalue()

    def test_clean_answer_has_no_retry(self):
        result, feedbacks, log = self.run_topic([_good_biweekly()])
        self.assertIsNotNone(result[0])
        self.assertEqual(feedbacks, [""])

    def test_the_tamil_letter_that_used_to_pass_now_retries_and_then_drops(self):
        bad = dict(_good_biweekly(), comparison_text_he=_good_biweekly()["comparison_text_he"] + " טראמப.")
        result, feedbacks, log = self.run_topic([bad, bad])
        self.assertIsNone(result[0])
        self.assertIn("text defect", log)
        self.assertIn("another writing system", feedbacks[1])

    def test_foreign_letters_in_the_english_text_are_checked_too(self):
        bad = dict(_good_biweekly(), comparison_text_en=_good_biweekly()["comparison_text_en"] + " ப")
        result, feedbacks, log = self.run_topic([bad, _good_biweekly()])
        self.assertIsNotNone(result[0])
        self.assertEqual(len(feedbacks), 2)

    def test_globe_and_mail_in_hebrew_letters_is_a_violation_now(self):
        bad = dict(_good_biweekly(), comparison_text_he=_good_biweekly()["comparison_text_he"] + " ואילו גלוב אנד מייל נשאר עובדתי.")
        result, feedbacks, log = self.run_topic([bad, _good_biweekly()])
        self.assertIsNotNone(result[0])
        self.assertIn("The Globe and Mail", feedbacks[1])

    def test_los_angeles_and_wall_street_as_places_no_longer_cost_a_retry(self):
        ok = dict(_good_biweekly(), comparison_text_he=_good_biweekly()["comparison_text_he"] + " הבורסה בוול סטריט והעיר לוס אנג'לס הושפעו, וגם טיימס סקוור.")
        result, feedbacks, log = self.run_topic([ok])
        self.assertIsNotNone(result[0])
        self.assertEqual(len(feedbacks), 1)

    def test_a_glued_prefix_is_repaired_and_counted_without_a_retry(self):
        glued = dict(_good_biweekly(), comparison_text_he=_good_biweekly()["comparison_text_he"] + " ובכתבה בSüddeutsche Zeitung נטען.")
        result, feedbacks, log = self.run_topic([glued])
        self.assertEqual(len(feedbacks), 1)
        self.assertIn("ב-Süddeutsche Zeitung", result[0]["comparison_text_he"])
        self.assertEqual(sb.BIWEEKLY_LOG_ONLY["prefix_hyphen"], 1)

    def test_markup_in_a_biweekly_text_retries(self):
        bad = dict(_good_biweekly(), comparison_text_he=_good_biweekly()["comparison_text_he"] + "</comparison_text_he>")
        result, feedbacks, log = self.run_topic([bad, _good_biweekly()])
        self.assertIsNotNone(result[0])
        self.assertIn("markup", feedbacks[1])


class OverviewCheckedTest(unittest.TestCase):
    TOPICS = [{"topic_label_en": "Topic", "n_distinct_days": 6, "n_sources": 3}]

    def good(self):
        return {"overview_he": "בתקופה הזו בלטו סיפורים חוזרים בסיקור של The Guardian ושל Die Welt, ובראשם משבר אחד מתמשך.",
                "overview_en": "Over the period several stories kept returning in the coverage of The Guardian and Die Welt.",
                "overview_de": "Im Berichtszeitraum kehrten mehrere Themen in der Berichterstattung von The Guardian und Die Welt wieder."}

    def run_overview(self, answers):
        feedbacks = []

        def fake(client, topics, feedback=""):
            feedbacks.append(feedback)
            return dict(answers.pop(0)), {}

        out = io.StringIO()
        with mock.patch.object(sb, "write_overview", side_effect=fake), contextlib.redirect_stdout(out):
            result = sb.write_overview_checked(None, self.TOPICS)
        return result, feedbacks, out.getvalue()

    def test_clean_overview_is_written_once(self):
        _, feedbacks, _ = self.run_overview([self.good()])
        self.assertEqual(feedbacks, [""])

    def test_overview_with_a_hebrew_letter_name_is_rewritten_once(self):
        bad = dict(self.good(), overview_he=self.good()["overview_he"] + " לפי הגארדיין.")
        (overview, _), feedbacks, _ = self.run_overview([bad, self.good()])
        self.assertEqual(len(feedbacks), 2)
        self.assertNotIn("גארדיין", overview["overview_he"])

    def test_overview_that_stays_bad_is_kept_and_warned_about(self):
        bad = dict(self.good(), overview_he=self.good()["overview_he"] + " טראמப.")
        (overview, _), feedbacks, log = self.run_overview([bad, bad])
        self.assertIn("טראמப", overview["overview_he"])
        self.assertIn("WARNING", log)


if __name__ == "__main__":
    unittest.main()
