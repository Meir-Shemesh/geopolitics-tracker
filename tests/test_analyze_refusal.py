"""Refusals in analyze.py (PROJECT_LOG 4.132): a page the model refuses (stop_reason == "refusal") is a final state.

The three real cases were pages 199, 410 and 552, which came back with an empty tool_use input (KeyError: 'articles'),
stayed 'pending' and failed again on every daily run.
"""

import json
import unittest
from types import SimpleNamespace

from src.analysis import analyze
from tests.test_analyze_batch import (REAL_ANALYZE_PAGE, USAGE, AnalyzeBatchTestBase, FakeBatches, answer_for, tool_entry)


def refusal_entry(custom_id):
    content = [SimpleNamespace(type="tool_use", input={})]
    return SimpleNamespace(custom_id=custom_id, result=SimpleNamespace(
        type="succeeded", message=SimpleNamespace(content=content, usage=SimpleNamespace(**USAGE), stop_reason="refusal")))


class RefusalTest(AnalyzeBatchTestBase):
    def refuse_page(self, page):
        return lambda cid: refusal_entry(cid) if analyze.parse_custom_id(cid)[1] == page else tool_entry(cid, answer_for(cid))

    def test_a_refused_batch_page_is_final_and_never_asked_again(self):
        fid = self.add_file(1, pages=3)
        self.batches.plan = self.refuse_page(2)
        out = self.run_analyze()
        self.assertEqual(self.regular_calls, [])  # no fallback to a regular call for the refused page
        states = self.page_states(fid)
        self.assertEqual(states[0][0], "completed")
        self.assertEqual(states[1][:2], ("refused", "refused"))
        self.assertEqual(states[2][0], "completed")
        note = self.query("SELECT analysis_note FROM page_screening WHERE file_id=? AND page_number=2", (fid,))[0][0]
        self.assertEqual(note, "stop_reason=refusal")
        self.assertEqual(self.query("SELECT COUNT(*) AS n FROM articles WHERE page_number=2")[0]["n"], 0)
        self.assertIn("Refused pages (1)", out)
        self.assertIn(f"refused page: file_id={fid} page=2", out)
        self.assertIn("2 page(s) analyzed, 0 page(s) failed", out)  # the Analysis line keeps its format
        self.assertNotIn("Failed pages", out)

    def test_the_next_run_does_not_see_the_page_as_pending(self):
        fid = self.add_file(1, pages=2)
        self.batches.plan = self.refuse_page(1)
        self.run_analyze()
        self.assertEqual([tuple(p)[:2] for p in db_pending(self.connect())], [])
        self.batches.created.clear()
        out = self.run_analyze()
        self.assertNotIn("Refused pages", out)
        self.assertEqual(self.batches.created, [])

    def test_a_refused_regular_call_is_final_too(self):
        fid = self.add_file(1, pages=2)
        self.fallback_plan = lambda ref: analyze.PageRefused(analyze.REFUSAL_REASON) if ref.endswith(":1") else answer_for(
            f"a-{ref.split(':')[0]}-p{ref.split(':')[1]}")
        out = self.run_analyze(use_batch=False)
        self.assertEqual(self.page_states(fid)[0][:2], ("refused", "refused"))
        self.assertEqual(self.page_states(fid)[1][0], "completed")
        self.assertIn("Refused pages (1)", out)
        self.assertEqual(self.regular_calls, [f"{fid}:1", f"{fid}:2"])  # asked once each

    def test_analyze_page_raises_page_refused_on_the_stop_reason(self):
        content = [SimpleNamespace(type="tool_use", input={})]
        response = SimpleNamespace(content=content, usage=SimpleNamespace(**USAGE), stop_reason="refusal")
        client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: response))
        with self.assertRaises(analyze.PageRefused):
            REAL_ANALYZE_PAGE(client, "Economist", "text")

    def test_the_record_file_lists_refused_pages(self):
        self.add_file(1, pages=1)
        self.batches.plan = self.refuse_page(1)
        self.run_analyze()
        files = list(self.flag_dir.glob("*.analyze_failed.json"))
        self.assertEqual(len(files), 1)
        data = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(data["runs"][0]["refused_pages"][0]["page_number"], 1)

    def test_batch_result_kind_is_refused(self):
        from src.common import batch_runner
        fake = FakeBatches(plan=lambda cid: refusal_entry(cid))
        fake.created.append(("b1", [{"custom_id": "a-1-p1"}]))
        results = batch_runner.fetch_results(SimpleNamespace(messages=SimpleNamespace(batches=fake)), "b1")
        self.assertEqual(results["a-1-p1"].kind, "refused")
        self.assertFalse(results["a-1-p1"].usable)


def db_pending(conn):
    from src.common import db
    return db.get_pages_pending_analysis(conn)


if __name__ == "__main__":
    unittest.main()
