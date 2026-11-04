"""The tile map replaces the old coverage-trends chart (PROJECT_LOG 4.123): the map takes the name the top navigation
already points at, the biweekly index moves to its own file, and the old chart URL becomes a short redirect page."""
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.publishing import publish, trends_map_page  # noqa: E402
from src.reporting.render_biweekly import build_biweekly_report_html  # noqa: E402

PERIOD = {"start_date": "2026-10-15", "end_date": "2026-10-28", **{f"overview_{lang}": "overview" for lang in ("he", "en", "de")}}
TOPIC = {"id": 1, "n_distinct_days": 5, "n_sources": 2, **{f"topic_label_{lang}": "label" for lang in ("he", "en", "de")},
         **{f"comparison_text_{lang}": "text" for lang in ("he", "en", "de")}}
DAYS = {1: ([{"section_id": 10, "report_date": "2026-10-15"}], ["The Guardian", "Die Welt"])}
LANG_LINK = re.compile(r'<a class="top-nav-link top-nav-lang-link" href="([^"]+)"')


class TrendsPageSwitchTest(unittest.TestCase):
    def test_the_old_chart_is_off_by_default_and_the_names_are_fixed(self):
        self.assertFalse(publish.LEGACY_TRENDS_CHART_ENABLED)
        self.assertEqual((publish.TRENDS_PAGE, publish.TRENDS_REPORTS_PAGE), ("trends.html", "trendsreports.html"))

    def test_the_old_url_serves_a_noindex_redirect_page_in_each_language(self):
        bodies = set()
        for lang, direction in (("he", "rtl"), ("en", "ltr"), ("de", "ltr")):
            html = publish.build_trends_chart_redirect_html(lang)
            self.assertIn(f'<html lang="{lang}" dir="{direction}">', html)
            self.assertIn('<meta name="robots" content="noindex">', html)
            self.assertIn('<meta http-equiv="refresh" content="0; url=trends.html">', html)
            self.assertIn('<a href="trends.html">', html)
            self.assertNotIn("chart-svg", html)  # none of the old page's script is in it
            bodies.add(publish._TRENDS_CHART_MOVED_LABELS[lang]["body"])
        self.assertEqual(len(bodies), 3)  # written per language, not one text three times

    def test_the_reports_index_has_no_card_to_the_old_chart_and_switches_language_within_itself(self):
        for lang in ("he", "en", "de"):
            html = publish.build_trends_hub_html(lang, [])
            self.assertNotIn("trendschart.html", html)
            hrefs = LANG_LINK.findall(html)
            self.assertEqual(sorted(hrefs), sorted(f"../{o}/trendsreports.html" for o in ("he", "en", "de") if o != lang))
            with mock.patch.object(publish, "LEGACY_TRENDS_CHART_ENABLED", True):
                self.assertIn('href="trendschart.html"', publish.build_trends_hub_html(lang, []))

    def test_the_reports_index_is_named_for_what_it_holds_and_links_back_to_the_map(self):
        titles = {"he": "דוחות מגמות דו-שבועיים", "en": "Biweekly Trends Reports", "de": "Zweiwöchentliche Trendberichte"}
        for lang, title in titles.items():
            html = publish.build_trends_hub_html(lang, [])
            self.assertIn(f'<h1 class="report-title">{title}</h1>', html)
            self.assertIn('<a class="chart-card map-card" href="trends.html">', html)  # the map
            tagline = publish._TRENDS_HUB_LABELS[lang]["tagline"]
            for word in ("גיא", "geograph", "Geograph", "geograf", "geografisch"):
                self.assertNotIn(word, tagline)  # the page does not promise a geographic analysis

    def test_the_link_cards_point_forward_in_the_reading_direction_of_each_language(self):
        labels = publish._TRENDS_HUB_LABELS
        self.assertTrue(labels["he"]["map_card_cta"].endswith("←"))
        for lang in ("en", "de"):
            self.assertTrue(labels[lang]["map_card_cta"].endswith("→"), lang)
        self.assertTrue(labels["de"]["tagline"].startswith("Berichte in Erzählform"))

    def test_the_map_page_under_the_trends_name_links_to_the_reports_index(self):
        for lang in ("he", "en", "de"):
            html = trends_map_page.build_trends_map_html(lang, page_name=publish.TRENDS_PAGE, reports_href=publish.TRENDS_REPORTS_PAGE)
            self.assertIn('<p class="reports-link"><a href="trendsreports.html">', html)
            self.assertEqual(sorted(LANG_LINK.findall(html)), sorted(f"../{o}/trends.html" for o in ("he", "en", "de") if o != lang))
            self.assertNotIn('<p class="reports-link">', trends_map_page.build_trends_map_html(lang))  # the link is opt-in

    def test_a_biweekly_report_goes_back_to_the_reports_index_not_the_map(self):
        for lang in ("he", "en", "de"):
            html = build_biweekly_report_html(PERIOD, [TOPIC], DAYS, lang)
            self.assertIn('href="trendsreports.html"', html)


if __name__ == "__main__":
    unittest.main()
