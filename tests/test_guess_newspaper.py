"""Tests for guess_newspaper() source recognition, focused on The Observer (PROJECT_LOG 4.110, corrected in 4.111).

The Observer is its own source ("Observer", displayed as "The Observer"), NOT the Guardian: Guardian Media Group sold it
to Tortoise Media in 2025. Sibling titles seen in the same channel that are not MVP sources (The Times UK, Welt am
Sonntag, NZZ am Sonntag) must stay unrecognized. File names are real names from the channel scan of
2026-07-14..2026-10-12 and the 2026-10-25 check.
"""

import unittest

from src.ingestion.fetch import guess_newspaper
from src.reporting.render import NEWSPAPER_DISPLAY_NAMES, NEWSPAPER_LANGUAGES
from src.reporting.synthesize import hebrew_newspaper_name_tells


class ObserverRecognitionTest(unittest.TestCase):
    def test_both_observer_file_name_formats_map_to_their_own_source(self):
        self.assertEqual(guess_newspaper("The Observer_2510.pdf"), "Observer")
        self.assertEqual(guess_newspaper("The Observer - 30 August 2026.pdf"), "Observer")

    def test_observer_is_not_merged_into_guardian(self):
        self.assertNotEqual(guess_newspaper("The Observer_2510.pdf"), "Guardian")

    def test_existing_guardian_editions_are_unchanged(self):
        self.assertEqual(guess_newspaper("The Guardian UK_2410.pdf"), "Guardian")
        self.assertEqual(guess_newspaper("The Guardian Weekly_2310.pdf"), "Guardian")

    def test_observer_needs_to_be_a_whole_word(self):
        self.assertIsNone(guess_newspaper("Preobserverlike_2510.pdf"))

    def test_observer_is_displayed_under_its_own_name_and_counted_as_english(self):
        self.assertEqual(NEWSPAPER_DISPLAY_NAMES["Observer"], "The Observer")
        self.assertEqual(NEWSPAPER_DISPLAY_NAMES["Guardian"], "The Guardian")
        self.assertEqual(NEWSPAPER_LANGUAGES["Observer"], "en")

    def test_hebrew_letter_spelling_of_the_name_is_flagged(self):
        self.assertIn("אובזרבר", hebrew_newspaper_name_tells("לפי אובזרבר הממשלה תיכשל"))
        self.assertEqual(hebrew_newspaper_name_tells("לפי The Observer הממשלה תיכשל"), {})


class NonMvpSiblingsStayUnrecognizedTest(unittest.TestCase):
    def test_times_uk_is_not_an_mvp_source(self):
        self.assertIsNone(guess_newspaper("The Times UK_2510.pdf"))
        self.assertIsNone(guess_newspaper("The Times UK - 9 October 2026.pdf"))

    def test_sunday_editions_that_were_excluded_on_purpose_stay_excluded(self):
        self.assertIsNone(guess_newspaper("Welt am Sonntag - 4 Oktober 2026.pdf"))
        self.assertIsNone(guess_newspaper("NZZ am Sonntag - 4 Oktober 2026.pdf"))

    def test_the_faz_sunday_edition_still_matches(self):
        self.assertEqual(
            guess_newspaper("Frankfurter Allgemeine Sonntags Zeitung - 25 Oktober 2026.pdf"),
            "Frankfurter Allgemeine Zeitung",
        )


class SpiegelVariantsTest(unittest.TestCase):
    """Decided 2026-11-19: separate titles of a source's publisher (children's magazine, Spiegel Wissen/Spezial, WSJ Magazine,
    USA Today Sports Weekly) are not the source itself. The file names below are the ones that reached the archive."""

    def test_non_newspaper_titles_of_a_publisher_are_not_recognised(self):
        for name in (
            "Dein Spiegel - 12.2026.pdf",
            "Dein_Spiegel_12.2026.pdf",
            "Dein_Spiegel_11.26.pdf",
            "Der Spiegel Wissen - Nr.2 2026.pdf",
            "Der Spiegel - Spezial Nr.2 2026.pdf",
            "The Wall Street Journal Magazine - Fall 2026.pdf",
            "WSJ Magazine - The Men's Style Issue, Fall 2026.pdf",
            "USA TODAY Sports Weekly_2608.pdf",
            "USA Today Sports Weekly - 23 September 2026.pdf",
            "USA Today Sports Weekly_3009.pdf",
        ):
            self.assertIsNone(guess_newspaper(name), name)

    def test_the_real_papers_still_match(self):
        for name, source in (
            ("Der Spiegel - 13.11.2026.pdf", "Der Spiegel"),
            ("Der_Spiegel_6.11.26.pdf", "Der Spiegel"),
            ("Der Spiegel - 30 Oktober 2026.pdf", "Der Spiegel"),
            ("Spiegel_2711.pdf", "Der Spiegel"),
            ("USA Today - November 18, 2026.pdf", "USA Today"),
            ("The Wall Street Journal - 23 October 2026.pdf", "Wall Street Journal"),
            ("WSJ_2708.pdf", "Wall Street Journal"),
        ):
            self.assertEqual(guess_newspaper(name), source, name)


class OtherSourcesUnchangedTest(unittest.TestCase):
    def test_wsj_is_still_identified_so_the_suspension_can_apply(self):
        self.assertEqual(guess_newspaper("The Wall Street Journal - 23 October 2026.pdf"), "Wall Street Journal")

    def test_nyt_is_still_never_returned(self):
        self.assertIsNone(guess_newspaper("NYT 1309.pdf"))
        self.assertIsNone(guess_newspaper("New York Times International - 12 September 2026.pdf"))

    def test_economist_web_edition_only(self):
        self.assertEqual(guess_newspaper("The Economist (Web Edition)_2410.pdf"), "Economist")
        self.assertIsNone(guess_newspaper("The Economist UK_2410.pdf"))


if __name__ == "__main__":
    unittest.main()
