"""Tile-map trends data (src/common/trends_map.py, PROJECT_LOG 4.123): the share definition, the named-only
denominator, the evidence rule, the strict baseline and the shape of trends_map.json. Temp DB, no API."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.common import db, trends, trends_map  # noqa: E402
from src.publishing import publish  # noqa: E402

WEEK1, WEEK2 = "2026-10-01", "2026-10-09"  # the week grid starts at the first report date: 10-01..10-07, 10-08..10-14


class TrendsMapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.get_connection(Path(self.tmp.name) / "t.db")
        db.init_db(self.conn)
        self.n = 0
        patcher = mock.patch.object(trends_map, "CORE_FIRST_WEEK_START", WEEK1)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def add(self, rdate, newspaper, headline, countries):
        self.n += 1
        db.mark_downloaded(self.conn, "t", self.n, f"f{self.n}.pdf", newspaper, f"{rdate}T10:00:00+00:00", f"{rdate}T10:00:00+00:00", "/x")
        self.conn.execute("UPDATE downloaded_files SET report_date = ? WHERE message_id = ?", (rdate, self.n))
        file_id = self.conn.execute("SELECT id FROM downloaded_files WHERE message_id = ?", (self.n,)).fetchone()["id"]
        article_id = db.insert_article(self.conn, file_id, 1, newspaper, "en", headline, "", "t", "", "", "2026-11-02T00:00:00")
        db.insert_article_countries(self.conn, article_id, countries)

    def counts(self):
        chunks = trends_map._week_grid(self.conn)
        rows = trends.get_country_article_rows(self.conn, named_only=True)
        return trends_map.paper_week_counts(rows, chunks)

    def test_share_is_the_mean_of_per_newspaper_shares_not_the_pooled_share(self):
        for _ in range(2):
            self.add(WEEK1, "Guardian", "France votes", ["FR"])
            self.add(WEEK1, "Guardian", "Germany votes", ["DE"])
        self.add(WEEK1, "Die Welt", "France votes", ["FR"])
        counts = self.counts()
        papers = ("Guardian", "Die Welt")
        shares, named, k, pairs = trends_map.equal_weight_shares(counts, papers, 0, ["FR", "DE"])
        self.assertEqual((k, pairs, named), (2, 5, {"FR": 3, "DE": 2}))
        self.assertAlmostEqual(shares["FR"], 75.0)  # mean(2/4, 1/1)
        self.assertAlmostEqual(shares["DE"], 25.0)
        self.assertAlmostEqual(trends_map.pooled_shares(counts, papers, 0, ["FR", "DE"])["FR"], 60.0)

    def test_an_unnamed_tag_is_in_neither_the_numerator_nor_the_denominator(self):
        self.add(WEEK1, "Guardian", "France votes", ["FR"])
        self.add(WEEK1, "Guardian", "Markets wobble", ["DE"])  # tagged DE, never names it
        shares, named, k, pairs = trends_map.equal_weight_shares(self.counts(), ("Guardian",), 0, ["FR", "DE"])
        self.assertEqual((pairs, named["DE"]), (1, 0))
        self.assertAlmostEqual(shares["FR"], 100.0)

    def test_a_paper_with_no_named_pair_that_week_is_not_averaged_in_as_zero(self):
        self.add(WEEK1, "Guardian", "France votes", ["FR"])
        shares, _, k, _ = trends_map.equal_weight_shares(self.counts(), ("Guardian", "Die Welt"), 0, ["FR"])
        self.assertEqual(k, 1)
        self.assertAlmostEqual(shares["FR"], 100.0)

    def test_nobody_reporting_gives_none_not_zero(self):
        shares, named, k, pairs = trends_map.equal_weight_shares(self.counts(), ("Guardian",), 0, ["FR"])
        self.assertEqual((shares["FR"], named["FR"], k, pairs), (None, 0, 0, 0))

    def test_low_evidence_when_the_week_or_the_baseline_is_thin(self):
        self.assertTrue(trends_map.is_low_evidence(1, 2))
        self.assertTrue(trends_map.is_low_evidence(1, 14))  # 0.1% -> 1.9% style jumps are not shown as changes
        self.assertTrue(trends_map.is_low_evidence(14, 1))
        self.assertTrue(trends_map.is_low_evidence(10, 0))
        self.assertFalse(trends_map.is_low_evidence(10, 10))  # exactly the minimum counts as enough
        self.assertTrue(trends_map.is_low_evidence(9.9, 40))
        self.assertTrue(trends_map.is_low_evidence(40, 9.9))
        self.assertFalse(trends_map.is_low_evidence(40, 40))

    def test_the_baseline_is_strict(self):
        self.assertEqual(trends_map.baseline_weeks(4, 3, 1), [3])
        self.assertEqual(trends_map.baseline_weeks(3, 3, 1), [])
        self.assertEqual(trends_map.baseline_weeks(6, 3, 4), [])  # only three earlier weeks exist
        self.assertEqual(trends_map.baseline_weeks(7, 3, 4), [3, 4, 5, 6])
        steps = [w for w in range(3, 11) if trends_map.baseline_weeks(w, 3, 4)]
        self.assertEqual(len(steps), 4)  # core series on the 2.11 data: 4 steps with a 4-week baseline, 7 with one

    def test_change_vs_baseline_is_percentage_points_against_the_mean_of_the_baseline_weeks(self):
        share = [None, None, None, 10.0, 12.0, 14.0, 16.0, 20.0]
        named = [0, 0, 0, 20, 20, 20, 20, 20]
        delta, low, _ = trends_map.change_vs_baseline(share, named, 7, 3, 4)
        self.assertAlmostEqual(delta, 20.0 - 13.0)
        self.assertFalse(low)
        _, mean_ok, _ = trends_map.change_vs_baseline(share, [0, 0, 0, 20, 20, 20, 3, 20], 7, 3, 4)
        self.assertFalse(mean_ok)  # the baseline is judged by its mean per week: (20+20+20+3)/4 = 15.75
        _, mean_thin, _ = trends_map.change_vs_baseline(share, [0, 0, 0, 20, 4, 4, 4, 20], 7, 3, 4)
        self.assertTrue(mean_thin)  # (20+4+4+4)/4 = 8 < 10
        delta, low, _ = trends_map.change_vs_baseline(share, named, 4, 3, 1)
        self.assertAlmostEqual(delta, 2.0)
        self.assertIsNone(trends_map.change_vs_baseline(share, named, 3, 3, 1))

    def test_a_change_whose_sign_differs_between_the_two_share_definitions_has_no_clear_direction(self):
        share = [None, None, None, 10.0, 12.0, 14.0, 16.0, 20.0]
        named = [0, 0, 0, 20, 20, 20, 20, 20]
        same = [None, None, None, 10.0, 11.0, 12.0, 13.0, 15.0]  # also rising
        opposite = [None, None, None, 20.0, 19.0, 18.0, 17.0, 14.0]  # falling
        _, _, unclear = trends_map.change_vs_baseline(share, named, 7, 3, 4, pooled=same)
        self.assertFalse(unclear)
        _, _, unclear = trends_map.change_vs_baseline(share, named, 7, 3, 4, pooled=opposite)
        self.assertTrue(unclear)
        _, _, unclear = trends_map.change_vs_baseline(share, named, 7, 3, 4)
        self.assertFalse(unclear)  # no pooled series given: nothing to compare with
        self.assertTrue(trends_map.signs_agree(1.5, 0.2))
        self.assertTrue(trends_map.signs_agree(-0.4, -3.0))
        self.assertFalse(trends_map.signs_agree(0.4, -0.1))
        self.assertFalse(trends_map.signs_agree(0.0, 0.1))  # zero under one definition, something under the other
        self.assertTrue(trends_map.signs_agree(0.0, 0.0))

    def test_the_tile_list_is_fixed_in_code_and_the_threshold_only_reports_what_to_review(self):
        for i in range(30):
            self.add(WEEK1, "Guardian", f"France story {i}", ["FR"])
        for i in range(29):
            self.add(WEEK1, "Die Welt", f"Germany story {i}", ["DE"])
        data = trends_map.build_trends_map(self.conn)
        self.assertEqual([t["code"] for t in data["tiles"]], sorted(trends_map.MAP_TILES))  # the same 36 whatever the data says
        self.assertNotIn("FR", data["tile_list"]["below_threshold"])  # 30 reaches the line
        self.assertIn("DE", data["tile_list"]["below_threshold"])  # 29 does not: kept, and listed for the monthly review
        self.assertEqual(data["tile_list"]["reviewed_on"], trends_map.TILE_LIST_REVIEWED_ON)
        cells = list(trends_map.MAP_TILES.values())
        self.assertEqual(len(cells), len(set(cells)))
        for col, row in cells:
            self.assertTrue(0 <= col < trends_map.MAP_GRID_COLS and 0 <= row < trends_map.MAP_GRID_ROWS)

    def test_json_shape_alignment_and_the_remainder(self):
        for i in range(30):
            self.add(WEEK1, "Guardian", f"France story {i}", ["FR"])
        self.add(WEEK1, "Guardian", "Brazil story", ["BR"])
        self.add(WEEK2, "Die Welt", "Frankreich story", ["FR"])
        data = trends_map.build_trends_map(self.conn, {"Guardian": "The Guardian"})
        n = len(data["weeks"])
        self.assertEqual(n, 2)
        self.assertEqual(data["counting"]["method"], "named_only")
        self.assertTrue(data["counting"]["lower_bound"])
        self.assertEqual(data["newspapers"]["Guardian"], "The Guardian")
        for key in ("core", "all"):
            block = data["series"][key]
            self.assertEqual(len(block["other_share"]), n)
            for series in block["countries"].values():
                self.assertEqual((len(series["share"]), len(series["n_named"])), (n, n))
        core = data["series"]["core"]
        self.assertEqual(core["first_week"], 0)
        week0 = sum(c["share"][0] for c in core["countries"].values()) + core["other_share"][0]
        self.assertAlmostEqual(week0, 100.0, places=2)  # the tiles plus every country without a tile are the whole pool
        self.assertEqual(set(core["per_paper"]), set(trends.CORE_V1))

    def test_the_core_series_is_empty_before_its_first_week(self):
        self.add(WEEK1, "Guardian", "France story", ["FR"])
        self.add(WEEK2, "Guardian", "France story", ["FR"])
        with mock.patch.object(trends_map, "CORE_FIRST_WEEK_START", "2026-10-08"):
            data = trends_map.build_trends_map(self.conn)
        core = data["series"]["core"]
        self.assertEqual(core["first_week"], 1)
        self.assertEqual(core["papers_reporting"][0], 0)
        self.assertIsNone(core["other_share"][0])

    def test_a_country_over_the_threshold_without_a_cell_is_reported_not_dropped_silently(self):
        for i in range(30):
            self.add(WEEK1, "Guardian", f"Finland story {i}", ["FI"])
        data = trends_map.build_trends_map(self.conn)
        self.assertNotIn("FI", [t["code"] for t in data["tiles"]])
        self.assertEqual(data["unplaced"], ["FI"])

    def test_the_page_opens_on_the_last_full_week_and_palestine_is_called_the_palestinians(self):
        for i in range(30):
            self.add(WEEK1, "Guardian", f"Palestinian story {i}", ["PS"])
        self.add("2026-10-08", "Guardian", "Palestinian story", ["PS"])
        self.add("2026-10-11", "Guardian", "Palestinian story", ["PS"])  # the second week has only four days of data
        data = trends_map.build_trends_map(self.conn)
        self.assertEqual([w["partial"] for w in data["weeks"]], [False, True])
        self.assertEqual(data["default_week"], 0)
        ps = next(t for t in data["tiles"] if t["code"] == "PS")
        self.assertEqual((ps["name_he"], ps["name_en"], ps["name_de"]), ("פלסטינים", "Palestinians", "Palästinenser"))
        self.assertEqual((ps["short_he"], ps["short_en"], ps["short_de"]), ("פלסטינים", "Palestinians", "Palästinenser"))
        self.assertEqual(trends_map.last_full_week([{"partial": False}, {"partial": False}, {"partial": True}]), 1)

    def test_the_payload_does_not_depend_on_insertion_order(self):
        def build(order):
            tmp = tempfile.TemporaryDirectory()
            conn = db.get_connection(Path(tmp.name) / "o.db")
            db.init_db(conn)
            held = (self.conn, self.n)
            self.conn, self.n = conn, 0
            try:
                for args in order:
                    self.add(*args)
                out = trends_map.build_trends_map(conn)
            finally:
                self.conn, self.n = held
                conn.close()
                tmp.cleanup()
            out.pop("generated_at")
            return out

        rows = [(WEEK1, "Guardian", f"France story {i}", ["FR"]) for i in range(30)] + [
            (WEEK1, "Die Welt", "Germany story", ["DE"]), (WEEK2, "Guardian", "France story", ["FR"])]
        self.assertEqual(build(rows), build(list(reversed(rows))))

    def test_publish_writes_the_payload_through_the_same_builder(self):
        for i in range(30):
            self.add(WEEK1, "Guardian", f"France story {i}", ["FR"])
        data = publish.build_trends_map_json(self.conn)
        self.assertEqual(data["newspapers"]["Guardian"], "The Guardian")
        self.assertEqual(publish.TRENDS_MAP_RELATIVE_PATH.name, "trends_map.json")


if __name__ == "__main__":
    unittest.main()
