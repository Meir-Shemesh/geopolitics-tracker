"""The biweekly report's language switcher must climb out of docs/{lang}/ into the other language's folder
(2026-10-29: it linked to a same-folder file name and 404'd on all six published periods)."""

import posixpath
import re
import unittest

from src.reporting.render_biweekly import build_biweekly_report_html, period_filename

START, END = "2026-10-15", "2026-10-28"
PERIOD = {
    "start_date": START,
    "end_date": END,
    **{f"overview_{lang}": "overview" for lang in ("he", "en", "de")},
}
TOPIC = {
    "id": 1,
    "n_distinct_days": 5,
    "n_sources": 2,
    **{f"topic_label_{lang}": "label" for lang in ("he", "en", "de")},
    **{f"comparison_text_{lang}": "text" for lang in ("he", "en", "de")},
}
DAYS = {1: ([{"section_id": 10, "report_date": "2026-10-15"}], ["The Guardian", "Die Welt"])}


class BiweeklyLangLinksTest(unittest.TestCase):
    def test_every_language_link_resolves_to_the_other_languages_period_file(self):
        for lang in ("he", "en", "de"):
            html = build_biweekly_report_html(PERIOD, [TOPIC], DAYS, lang)
            hrefs = re.findall(r'<a class="top-nav-link top-nav-lang-link" href="([^"]+)"', html)
            self.assertEqual(len(hrefs), 2, lang)
            resolved = {posixpath.normpath(posixpath.join("docs", lang, h)) for h in hrefs}
            expected = {f"docs/{o}/{period_filename(START, END, o)}" for o in ("he", "en", "de") if o != lang}
            self.assertEqual(resolved, expected, lang)


if __name__ == "__main__":
    unittest.main()
