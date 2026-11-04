"""The home-page miniature of the trends map (trends_map.build_trends_map_mini, trends_map_mini.json, the map tile in
publish.build_homepage_html): it must colour exactly what the map colours, show no figures, ignore the partial week
and fail quietly. No API, no tracker.db."""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.common import db, trends_map  # noqa: E402
from src.publishing import publish, trends_map_page  # noqa: E402

N = 4  # weeks 0..3; week 3 is partial. The core series starts at week 1 (so week 2 is the default, week 1 its baseline).


def tile(code, col, row):
    return {"code": code, "col": col, "row": row}


def country(share, named, pooled):
    return {"share": share, "n_named": named, "pooled_share": pooled}


def wk(base, now):
    """A share series: the baseline in week 1, the default week 2, and a partial week 3 that must never be read."""
    return [None, base, now, now]


def sample_data():
    return {
        "counting": {"min_evidence_articles": 10},
        "grid": {"cols": 14, "rows": 7},
        "default_week": 2,
        "weeks": [{"start": f"2026-10-{1 + 7 * i:02d}", "end": f"2026-10-{7 + 7 * i:02d}", "partial": i == 3} for i in range(N)],
        "tiles": [tile("UP", 0, 0), tile("DN", 1, 0), tile("FL", 2, 0), tile("TH", 3, 0), tile("TB", 4, 0),
                  tile("UC", 5, 0), tile("NB", 6, 0), tile("BG", 7, 0), tile("PW", 8, 0)],
        "series": {"core": {"first_week": 1, "countries": {
            "UP": country(wk(4.0, 9.0), [0, 20, 20, 20], wk(4.0, 9.0)),
            "DN": country(wk(8.0, 6.0), [0, 20, 20, 20], wk(8.0, 6.0)),
            "FL": country(wk(5.0, 5.0), [0, 20, 20, 20], wk(5.0, 5.0)),
            "TH": country(wk(1.0, 3.0), [0, 20, 3, 20], wk(1.0, 3.0)),       # thin week
            "TB": country(wk(1.0, 3.0), [0, 3, 20, 20], wk(1.0, 3.0)),       # thin baseline
            "UC": country(wk(4.0, 5.0), [0, 20, 20, 20], wk(5.0, 4.0)),      # the two definitions disagree
            "NB": country([None, 5.0, None, None], [0, 20, 0, 0], [None, 5.0, None, None]),                       # nothing in the week
            "BG": country(wk(0.5, 9.0), [0, 20, 20, 20], wk(0.5, 9.0)),      # a huge change: full colour
            "PW": country(wk(1.0, 1.0), [0, 20, 20, 20], wk(1.0, 1.0)),
        }}},
    }


class MiniBuilderTest(unittest.TestCase):
    def setUp(self):
        self.data = sample_data()
        self.mini = trends_map.build_trends_map_mini(self.data)
        self.by = {t["c"]: t for t in self.mini["tiles"]}

    def expected_state(self, code):
        """What the map draws for the tile in the same view: the map's own rules (change_vs_baseline), one week back."""
        c = self.data["series"]["core"]["countries"][code]
        res = trends_map.change_vs_baseline(c["share"], c["n_named"], self.data["default_week"], 1, 1, 10, c["pooled_share"])
        if res is None:
            return "none"
        delta, thin, unclear = res
        if thin or unclear:
            return "low"
        return "colour+" if delta > 0 else "colour-" if delta < 0 else "flat"

    def test_every_tile_is_drawn_as_the_map_draws_it(self):
        for t in self.data["tiles"]:
            s = self.by[t["code"]]["s"]
            got = s if isinstance(s, str) else ("colour+" if s > 0 else "colour-" if s < 0 else "flat")
            self.assertEqual(got, self.expected_state(t["code"]), t["code"])

    def test_the_cases_that_must_not_be_coloured_are_striped(self):
        for code in ("TH", "TB", "UC"):
            self.assertEqual(self.by[code]["s"], "low", code)
        self.assertEqual(self.by["NB"]["s"], "none")
        self.assertGreater(self.by["UP"]["s"], 0)
        self.assertLess(self.by["DN"]["s"], 0)
        self.assertEqual(self.by["FL"]["s"], 0)

    def test_the_colour_step_follows_the_maps_intensity(self):
        self.assertEqual(self.by["BG"]["s"], trends_map.MINI_STEPS)            # |8.5| pp is past full scale
        self.assertEqual(trends_map.mini_bucket(trends_map.FULL_SCALE_PP), trends_map.MINI_STEPS)
        self.assertEqual(trends_map.mini_bucket(-trends_map.FULL_SCALE_PP), -trends_map.MINI_STEPS)
        self.assertEqual(trends_map.mini_bucket(0.0), 0)
        self.assertEqual(trends_map.mini_bucket(0.0001), 0)
        self.assertEqual(trends_map.mini_bucket(-0.9), -trends_map.mini_bucket(0.9))
        steps = [trends_map.mini_bucket(d / 10) for d in range(0, 36)]
        self.assertEqual(steps, sorted(steps))                                    # more change, never less colour

    def test_the_constants_match_the_page(self):
        m = re.search(r"var FULL_SCALE_PP = ([\d.]+);", trends_map_page._JS)
        self.assertEqual(float(m.group(1)), trends_map.FULL_SCALE_PP)
        self.assertIn('state = { series: "core", base: 1,', trends_map_page._JS)
        self.assertEqual((trends_map.MINI_SERIES, trends_map.MINI_BASE), ("core", 1))

    def test_the_opening_week_is_the_default_week_never_the_partial_one(self):
        self.assertEqual((self.mini["week_start"], self.mini["week_end"]), ("2026-10-15", "2026-10-21"))
        self.assertTrue(self.data["weeks"][3]["partial"])

    def test_no_figures_and_no_names_only_a_state_per_tile(self):
        self.assertEqual(set(self.mini), {"week_start", "week_end", "grid", "steps", "tiles"})
        for t in self.mini["tiles"]:
            self.assertEqual(set(t), {"c", "x", "y", "s"})
            self.assertTrue(isinstance(t["s"], int) or t["s"] in ("low", "none"))
        self.assertLess(len(json.dumps(self.mini, separators=(",", ":"))), 2000)

    def test_without_data_there_is_no_miniature(self):
        self.assertEqual(trends_map.build_trends_map_mini({}), {})


class RolloverTest(unittest.TestCase):
    """The day a partial week becomes a full one (the report of the week's last day arrives), both the map's opening
    week and the home-page miniature move to it - a temp DB with one more report date."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.get_connection(Path(self.tmp.name) / "t.db")
        db.init_db(self.conn)
        self.n = 0
        patcher = mock.patch.object(trends_map, "CORE_FIRST_WEEK_START", "2026-10-01")
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def add(self, rdate, headline="Palestinian story"):
        self.n += 1
        db.mark_downloaded(self.conn, "t", self.n, f"f{self.n}.pdf", "Guardian", f"{rdate}T10:00:00+00:00", f"{rdate}T10:00:00+00:00", "/x")
        self.conn.execute("UPDATE downloaded_files SET report_date = ? WHERE message_id = ?", (rdate, self.n))
        file_id = self.conn.execute("SELECT id FROM downloaded_files WHERE message_id = ?", (self.n,)).fetchone()["id"]
        article_id = db.insert_article(self.conn, file_id, 1, "Guardian", "en", headline, "", "t", "", "", "2026-11-02T00:00:00")
        db.insert_article_countries(self.conn, article_id, ["PS"])

    def test_the_latest_full_week_moves_forward_when_the_closing_report_date_arrives(self):
        for _ in range(12):
            self.add("2026-10-01")
        self.add("2026-10-08")
        self.add("2026-10-11")                      # the second week has four days of data: partial
        before = trends_map.build_trends_map(self.conn)
        self.assertEqual([w["partial"] for w in before["weeks"]], [False, True])
        self.assertEqual(before["default_week"], 0)
        mini = trends_map.build_trends_map_mini(before)
        self.assertEqual((mini["week_start"], mini["week_end"]), ("2026-10-01", "2026-10-07"))
        self.assertLessEqual({t["s"] for t in mini["tiles"]}, {"none"})    # week 0 has no baseline: any tile is drawn striped

        self.add("2026-10-14")                      # the report that completes the week arrives
        after = trends_map.build_trends_map(self.conn)
        self.assertEqual([w["partial"] for w in after["weeks"]], [False, False])
        self.assertEqual(after["default_week"], 1)
        mini = trends_map.build_trends_map_mini(after)
        self.assertEqual((mini["week_start"], mini["week_end"]), ("2026-10-08", "2026-10-14"))
        self.assertEqual(mini["week_end"], after["weeks"][1]["end"])


class MiniTileTest(unittest.TestCase):
    def test_the_tile_text_and_link_are_server_rendered_and_the_miniature_fails_quietly(self):
        src = Path(publish.__file__).read_text(encoding="utf-8")
        for needle in ('id="mapmini-svg"', 'aria-hidden="true" focusable="false" hidden', 'class="mapmini-beta"', 'id="mapmini-week" hidden'):
            self.assertIn(needle, src)
        js = publish._HOMEPAGE_JS_TEMPLATE
        part = js[js.index("function renderMapMini"):js.index("renderMapMini();")]
        self.assertIn(".catch(function () {})", part)          # a failed fetch changes nothing and logs nothing
        self.assertNotIn("console.", part)
        self.assertIn("if (!r.ok) throw", part)
        self.assertIn('svg.removeAttribute("hidden")', part)              # shown only after a good payload
        self.assertNotIn("delta", part)                        # the tile never carries a change figure
        self.assertEqual(publish.TRENDS_MAP_MINI_RELATIVE_PATH.name, "trends_map_mini.json")

    def test_the_biweekly_range_stays_on_one_line_and_shrinks_with_its_tile(self):
        css = publish.cta_card_css()
        self.assertIn("white-space: nowrap", css[css.index(".cta-card-number.is-range"):])
        self.assertIn(".cta-module { container-type: inline-size; }", css)
        self.assertRegex(css, r"min\(2\.1rem, [\d.]+cqw\)")

    def test_the_week_caption_has_all_three_languages(self):
        src = Path(publish.__file__).read_text(encoding="utf-8")
        for text in ('"שבוע {from} עד {to}"', '"Week of {from} to {to}"', '"Woche {from} bis {to}"', '"בטא"', '"Zur Karte →"', '"View map →"', '"למפה ←"'):
            self.assertIn(text, src)


if __name__ == "__main__":
    unittest.main()
