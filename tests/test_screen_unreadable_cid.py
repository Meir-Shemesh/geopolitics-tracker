"""Pages that are (cid:N) noise with under 100 real characters are marked not relevant without an API call, in the batch
path and the regular path alike (PROJECT_LOG 4.132). Reuses the screen-batch test base (fake client, temp SQLite)."""

import unittest

from src.analysis import screen
from tests.test_screen_batch import ScreenBatchTestBase, page_text

CID_NOISE = " ".join(f"(cid:{n})" for n in range(1, 120))
AD_PAGE = CID_NOISE + "\nSALE 50% OFF\n" + CID_NOISE


class UnitTest(unittest.TestCase):
    def test_real_char_count_removes_cid_tokens_and_collapses_whitespace(self):
        self.assertEqual(screen.real_char_count("(cid:1)(cid:22)  ab \n (cid:333) cd"), len("ab cd"))
        self.assertEqual(screen.real_char_count(None), 0)

    def test_unreadable_needs_cid_tokens_and_under_100_real_characters(self):
        self.assertTrue(screen.is_unreadable_cid(AD_PAGE))
        self.assertTrue(screen.is_unreadable_cid("(cid:5)"))
        self.assertFalse(screen.is_unreadable_cid("A short page with no glyph codes at all."))  # not the cid case
        self.assertFalse(screen.is_unreadable_cid(""))
        self.assertFalse(screen.is_unreadable_cid(None))

    def test_the_threshold_is_100_real_characters(self):
        ok = "x" * 100
        under = "x" * 99
        self.assertFalse(screen.is_unreadable_cid(f"(cid:1) {ok}"))
        self.assertTrue(screen.is_unreadable_cid(f"(cid:1) {under}"))

    def test_a_readable_page_with_many_cid_tokens_is_not_unreadable(self):
        self.assertFalse(screen.is_unreadable_cid(CID_NOISE + " " + page_text("rel", 1)))


class PathsTest(ScreenBatchTestBase):
    def seed(self) -> int:
        fid = self.add_file()
        self.add_page(fid, 1, page_text("rel", 1))
        self.add_page(fid, 2, AD_PAGE)
        self.add_page(fid, 3, page_text("sports", 3))
        return fid

    def check_rows(self):
        rows = {r[1]: r for r in self.rows()}
        self.assertEqual(len(rows), 3)
        cid_row = rows[2]
        self.assertEqual(cid_row[2], 0)  # is_relevant
        self.assertTrue(cid_row[3].startswith("unreadable (cid)"))
        self.assertEqual(cid_row[4], screen.UNREADABLE_CID_MODEL)
        self.assertEqual(cid_row[5], "pending")  # same as the empty-page branch: not relevant, nothing to analyze
        self.assertEqual(rows[1][2], 1)  # the real pages are screened as usual
        self.assertEqual(rows[3][2], 0)

    def test_regular_path_does_not_call_the_model_for_the_cid_page(self):
        fid = self.seed()
        self.run_screen(use_batch=False)
        self.assertEqual(self.api_calls, [f"{fid}:1", f"{fid}:3"])
        self.check_rows()

    def test_batch_path_does_not_send_the_cid_page(self):
        self.seed()
        self.run_screen(use_batch=True)
        sent = [r["custom_id"] for _bid, reqs in self.batches.created for r in reqs]
        self.assertEqual(len(sent), 2)
        self.assertFalse(any(s.endswith("p2") or s.endswith("-2") for s in sent), sent)
        self.assertEqual(self.api_calls, [])  # no regular-call fallback either
        self.check_rows()

    def test_both_paths_write_identical_rows(self):
        self.seed()
        self.run_screen(use_batch=False)
        off = self.rows()
        self.conn.execute("DELETE FROM page_screening")
        self.conn.commit()
        self.run_screen(use_batch=True)
        self.assertEqual([r[:5] for r in self.rows()], [r[:5] for r in off])


if __name__ == "__main__":
    unittest.main()
