"""Tests for guess_newspaper() source recognition, focused on the Observer addition (PROJECT_LOG 4.110).

The Observer is the Guardian's Sunday paper: it maps to the existing "Guardian" key. Sibling titles seen in the
same channel that are NOT MVP sources (The Times UK, Welt am Sonntag, NZZ am Sonntag) must stay unrecognized.
File names below are real names from the channel scan of 2026-07-14..2026-10-12 and the 2026-10-25 check.
"""

import unittest

from src.ingestion.fetch import guess_newspaper


class ObserverRecognitionTest(unittest.TestCase):
    def test_both_observer_file_name_formats_map_to_guardian(self):
        self.assertEqual(guess_newspaper("The Observer_2510.pdf"), "Guardian")
        self.assertEqual(guess_newspaper("The Observer - 30 August 2026.pdf"), "Guardian")

    def test_existing_guardian_editions_are_unchanged(self):
        self.assertEqual(guess_newspaper("The Guardian UK_2410.pdf"), "Guardian")
        self.assertEqual(guess_newspaper("The Guardian Weekly_2310.pdf"), "Guardian")

    def test_observer_needs_to_be_a_whole_word(self):
        self.assertIsNone(guess_newspaper("Preobserverlike_2510.pdf"))


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
