"""trendsmap.html (src/publishing/trends_map_page.py, PROJECT_LOG 4.123): the three languages carry the same labels and
placeholders, the product owner's Hebrew sentence is verbatim, and the built page has everything the script needs.
Structural only - colours, contrast and the drawing are checked in a real browser (screenshots), and the page's
arithmetic against trends_map.change_vs_baseline by driving the table view (see the 4.123 report)."""
import re
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.publishing import trends_map_page as page  # noqa: E402

HE_LOWER_BOUND = "הספירה כוללת רק כתבות שבהן המדינה נזכרת במפורש, ולכן המספרים הם גבול תחתון."
PLACEHOLDER = re.compile(r"\{(\w+)\}")


class TrendsMapPageTest(unittest.TestCase):
    def test_the_three_languages_have_the_same_keys_and_placeholders(self):
        keys = {lang: set(labels) for lang, labels in page.LABELS.items()}
        self.assertEqual(keys["he"], keys["en"])
        self.assertEqual(keys["he"], keys["de"])
        for key in keys["he"]:
            found = {lang: set(PLACEHOLDER.findall(page.LABELS[lang][key])) for lang in page.LABELS}
            self.assertEqual(found["he"], found["en"], key)
            self.assertEqual(found["he"], found["de"], key)

    def test_the_hebrew_lower_bound_sentence_is_the_approved_text_and_the_others_are_written_separately(self):
        self.assertEqual(page.LABELS["he"]["callout_lower_bound"], HE_LOWER_BOUND)
        self.assertIn("lower bound", page.LABELS["en"]["callout_lower_bound"])
        self.assertIn("Untergrenze", page.LABELS["de"]["callout_lower_bound"])

    def test_no_long_dashes_in_the_prose(self):
        for lang, labels in page.LABELS.items():
            for key, text in labels.items():
                self.assertNotIn("—", text, (lang, key))
                self.assertNotIn("–", text, (lang, key))

    def test_every_page_is_complete(self):
        for lang, direction in (("he", "rtl"), ("en", "ltr"), ("de", "ltr")):
            html = page.build_trends_map_html(lang)
            self.assertIn(f'<html lang="{lang}" dir="{direction}">', html)
            for element_id in ("m-map", "m-range", "m-play", "m-weekLabel", "m-base1", "m-base4", "m-series_core",
                               "m-series_all", "m-risingList", "m-fadingList", "m-selText", "m-tableBody"):
                self.assertIn(f'id="{element_id}"', html, (lang, element_id))
            self.assertNotRegex(html, r"__[A-Z_]+__", lang)
            self.assertIn(page.LABELS[lang]["callout_lower_bound"], html)
            self.assertIn("../assets/data/trends_map.json", html)
            self.assertIn('<button type="button" class="play-btn"', html)  # a real button, not a styled div
            self.assertIn('<path d="M', html)  # the world outline is embedded

    def test_a_tile_without_a_clear_direction_is_explained_in_every_language_and_the_script_checks_the_pooled_sign(self):
        for lang, labels in page.LABELS.items():
            for key in ("selected_unclear", "tile_aria_unclear", "unclear_mark"):
                self.assertTrue(labels[key].strip(), (lang, key))
        self.assertEqual(page.LABELS["he"]["legend_low"], "לא נצבע: ראיות מעטות או כיוון לא ברור")
        html = page.build_trends_map_html("en")
        self.assertIn("pooled_share", html)
        self.assertIn("function fitNames", html)  # long tile names shrink to fit instead of running off the tile

    def test_cards_for_striped_countries_show_no_number_and_german_numbers_use_a_decimal_comma(self):
        for lang, labels in page.LABELS.items():
            for key in ("selected_low", "selected_unclear"):
                self.assertNotIn("{delta}", labels[key], (lang, key))  # no change figure for a country that is not colored
            self.assertIn("{n}", labels["selected_n"], lang)
            self.assertIn("{base_n}", labels["selected_n_both"], lang)
            self.assertIn("{base_n}", labels["selected_n_both_1"], lang)
            self.assertNotIn("05d105de05de05d505e605e2", labels["selected_n_both_1"], lang)
        self.assertEqual(page.LABELS["de"]["base_4"], "Vorherige 4 Wochen")
        self.assertEqual(page.LABELS["de"]["base_text_4"], "im Schnitt der vier Vorwochen")
        self.assertEqual(page.LABELS["he"]["col_base"], "החלק בתקופת ההשוואה")
        de, he = page.build_trends_map_html("de"), page.build_trends_map_html("he")
        for html in (de, he):
            self.assertIn("new Intl.NumberFormat", html)
            self.assertNotIn("toFixed", html)  # every figure goes through the page-language formatter
            self.assertIn('document.createElement("bdi")', html)  # signed numbers in running text are isolated
        self.assertIn("&minus;3,5", de)
        self.assertIn("&minus;3.5", he)
        self.assertIn('"de-DE" : "en-US"', de)

    def test_the_outline_asset_is_one_closed_path_on_the_sketch_grid(self):
        path = page._outline_path()
        self.assertTrue(path.startswith("M"))
        self.assertTrue(path.endswith("Z"))
        self.assertNotIn("\n", path)


if __name__ == "__main__":
    unittest.main()
