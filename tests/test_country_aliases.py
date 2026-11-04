"""Country aliases for the conservative trends display (PROJECT_LOG 4.122). Pure text, no DB."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import country_aliases as ca  # noqa: E402
from src.common.geo_taxonomy import COUNTRY_LIST  # noqa: E402


def named(text):
    return ca.named_countries(text)


class CoverageTest(unittest.TestCase):
    def test_every_taxonomy_country_has_a_name_alias_and_nothing_else_does(self):
        self.assertEqual(set(ca.NAME_ALIASES), set(COUNTRY_LIST))
        self.assertLessEqual(set(ca.DEMONYMS), set(COUNTRY_LIST))

    def test_the_official_english_and_german_names_are_aliases(self):
        skipped = {"GE", "CD", "MD", "CZ", "GB", "AE", "US", "NZ"}  # bare Georgia is left out on purpose; the rest differ in form
        for code, info in COUNTRY_LIST.items():
            if code in skipped:
                continue
            self.assertIn(code, named(info["name_en"]), code)
            self.assertIn(code, named(info["name_de"]), code)

    def test_the_skipped_names_are_covered_by_their_own_forms(self):
        self.assertIn("GE", named("Georgien und Tbilisi"))
        self.assertNotIn("GE", named("The state of Georgia"))
        self.assertIn("CD", named("Demokratische Republik Kongo"))
        self.assertIn("MD", named("Republik Moldau"))
        self.assertIn("CZ", named("Tschechien"))
        self.assertIn("GB", named("Vereinigtes Königreich"))
        self.assertIn("AE", named("Vereinigte Arabische Emirate"))
        self.assertIn("NZ", named("Neuseeland"))
        self.assertIn("US", named("Vereinigte Staaten"))


class MatchingTest(unittest.TestCase):
    def test_name_possessive_and_german_genitive(self):
        self.assertEqual(named("Russia's economy"), {"RU"})
        self.assertEqual(named("Russlands Wirtschaft"), {"RU"})

    def test_capital_and_government_metonym(self):
        self.assertEqual(named("The Kremlin answered Beijing"), {"RU", "CN"})
        self.assertEqual(named("Teheran und Peking"), {"IR", "CN"})

    def test_demonym_lowercase_in_a_german_sentence(self):
        self.assertEqual(named("Die iranischen Raketen trafen die ukrainische Stadt"), {"IR", "UA"})

    def test_demonym_capitalised_at_the_start_of_a_german_headline(self):
        self.assertEqual(named("Iranische Raketen auf Charkiw"), {"IR"})
        self.assertEqual(named("Deutsche Waffen für Kiew"), {"DE", "UA"})

    def test_english_demonym(self):
        self.assertEqual(named("An Israeli strike and a Palestinian response"), {"IL", "PS"})

    def test_matching_is_case_sensitive_for_proper_nouns(self):
        self.assertEqual(named("They polish the table and eat turkey"), set())

    def test_south_sudan_is_not_sudan_and_the_washington_post_is_not_the_us(self):
        self.assertEqual(named("South Sudan talks"), {"SS"})
        self.assertEqual(named("Südsudan und Sudan"), {"SS", "SD"})
        self.assertEqual(named("Reported by the Washington Post"), set())

    def test_leaders_and_parties_are_deliberately_not_aliases(self):
        self.assertEqual(named("Trump, Putin and Netanjahu met Merz of the AfD"), set())

    def test_word_boundaries(self):
        self.assertEqual(named("Chinatown and Iranwhatever"), set())

    def test_article_text_reads_exactly_three_fields_and_tolerates_none(self):
        text = ca.article_text("Kyiv", None, "Berlin")
        self.assertEqual(named(text), {"UA", "DE"})


if __name__ == "__main__":
    unittest.main()
