"""Diagnostic logging added 2026-11-19 (no change of logic): the before/after snippet of every prefix-hyphen repair, and for the
biweekly reduce the attempt number, stop_reason and tokens of every call plus the raw answer that was not used.

No API, no tracker.db: a fake model client and a temporary review_flags directory."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tests"))

from src.reporting import synthesize as syn  # noqa: E402
from src.reporting import synthesize_biweekly as sb  # noqa: E402
from src.reporting import text_checks as tc  # noqa: E402
from test_biweekly_reduce import FakeClient, fake_response, sections  # noqa: E402

GLUED = "הסיקור ב" + "Süddeutsche Zeitung חריף, ואילו של" + "Los Angeles Times מתון."


class PrefixSnippetTest(unittest.TestCase):
    def test_a_repair_is_reported_with_its_surroundings(self):
        text = "בטור ב" + "Süddeutsche Zeitung נכתב כך."
        (pair,) = tc.attached_prefix_repairs(text)
        self.assertEqual(pair[0], text)
        self.assertEqual(pair[1], "בטור ב-Süddeutsche Zeitung נכתב כך.")

    def test_a_two_letter_word_gets_a_space_in_the_snippet_like_in_the_repair(self):
        pairs = tc.attached_prefix_repairs(GLUED)
        self.assertEqual(len(pairs), 2)
        self.assertIn("ב-Süddeutsche", pairs[0][1])
        self.assertIn("של Los Angeles", pairs[1][1])

    def test_the_snippets_match_the_repair_count_and_do_not_change_the_text(self):
        fixed, n = tc.fix_attached_prefixes(GLUED)
        self.assertEqual(n, len(tc.attached_prefix_repairs(GLUED)))
        self.assertEqual(tc.fix_attached_prefixes(GLUED), (fixed, n))   # repair unchanged

    def test_clean_text_has_no_snippets(self):
        self.assertEqual(tc.attached_prefix_repairs("בטור ב-The Guardian נכתב כך."), [])
        self.assertEqual(tc.attached_prefix_repairs(""), [])
        self.assertEqual(tc.attached_prefix_repairs(None), [])

    def test_the_snippet_is_one_line(self):
        (pair,) = tc.attached_prefix_repairs("שורה\nב" + "Süddeutsche Zeitung\nשורה")
        self.assertNotIn("\n", pair[0] + pair[1])


class DailyAndBiweeklyLogTest(unittest.TestCase):
    def test_the_daily_summary_prints_every_repair(self):
        syn.STAGE2_PREFIX_FIXES.clear()
        out = syn._finish_comparison({"topic_label_en": "Topic A"}, {"comparison_text_he": GLUED})
        self.assertIn("ב-Süddeutsche", out["comparison_text_he"])
        self.assertEqual(len(syn.STAGE2_PREFIX_FIXES), 2)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), mock.patch.object(syn, "summarize_api_usage", return_value={"cost": 0.0}):
            syn.print_stage2_summary("1970-01-01")   # the usage lookup is mocked: no tracker.db is opened
        printed = buf.getvalue()
        self.assertIn("prefix hyphen fix [Topic A]", printed)
        self.assertIn("-> ", printed)
        syn.STAGE2_PREFIX_FIXES.clear()

    def test_the_biweekly_topic_logs_the_field_and_both_sides(self):
        sb.BIWEEKLY_PREFIX_FIXES.clear()
        result = {"topic_label_en": "Topic B", "topic_label_he": "נושא", "comparison_text_he": GLUED,
                  "comparison_text_en": "x", "comparison_text_de": "y"}
        sb._finish_biweekly_result(result)
        self.assertEqual(len(sb.BIWEEKLY_PREFIX_FIXES), 2)
        self.assertTrue(all(line.startswith("[Topic B] comparison_text_he:") for line in sb.BIWEEKLY_PREFIX_FIXES))
        self.assertIn("ב-Süddeutsche", sb.BIWEEKLY_PREFIX_FIXES[0])
        sb.BIWEEKLY_PREFIX_FIXES.clear()

    def test_a_clean_biweekly_topic_logs_nothing(self):
        sb.BIWEEKLY_PREFIX_FIXES.clear()
        sb._finish_biweekly_result({"topic_label_he": "נושא", "comparison_text_he": "בטור ב-The Guardian.",
                                    "comparison_text_en": "x", "comparison_text_de": "y"})
        self.assertEqual(sb.BIWEEKLY_PREFIX_FIXES, [])


class ReduceAttemptLogTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.flags = Path(tmp.name)
        for target, kwargs in (("REVIEW_FLAGS_DIR", {"new": self.flags}),):
            p = mock.patch.object(sb, target, **kwargs)
            p.start()
            self.addCleanup(p.stop)
        for name, value in (("count_tokens", 1234), ("record_usage", None), ("record_biweekly_reduce_run", None)):
            p = mock.patch.object(sb, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def reduce(self, client, n=10):
        secs = sections(n)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sb.run_reduce(client, [("W1", [{"topic_label_en": "a", "section_ids": list(secs)}])], secs,
                          period=("2026-11-05", "2026-11-18"))
        return buf.getvalue()

    def rejected_file(self):
        return self.flags / "2026-11-18.biweekly_reduce_rejected.json"

    def test_every_call_logs_attempt_stop_reason_and_tokens(self):
        bad = [{"topic_label_en": "a", "section_ids": [1]}]
        good = [{"topic_label_en": "a", "section_ids": list(range(1, 11))}]
        out = self.reduce(FakeClient([fake_response(bad, output_tokens=55), fake_response(good, output_tokens=77)]))
        self.assertIn("[reduce call attempt 1] stop_reason='tool_use', input_tokens=100, output_tokens=55", out)
        self.assertIn("[reduce call attempt 2] stop_reason='tool_use', input_tokens=100, output_tokens=77", out)

    def test_a_clean_first_attempt_logs_once_and_saves_nothing(self):
        good = [{"topic_label_en": "a", "section_ids": list(range(1, 11))}]
        out = self.reduce(FakeClient([fake_response(good)]))
        self.assertEqual(out.count("[reduce call attempt"), 1)
        self.assertFalse(self.rejected_file().exists())

    def test_when_the_retry_improves_the_first_answer_is_saved(self):
        bad = [{"topic_label_en": "a", "section_ids": [1, 2]}]
        good = [{"topic_label_en": "a", "section_ids": list(range(1, 11))}]
        self.reduce(FakeClient([fake_response(bad, output_tokens=55), fake_response(good)]))
        data = json.loads(self.rejected_file().read_text(encoding="utf-8"))
        self.assertEqual((data["rejected_attempt"], data["used_attempt"]), (1, 2))
        self.assertEqual((data["stop_reason"], data["input_tokens"], data["output_tokens"]), ("tool_use", 100, 55))
        self.assertEqual(data["missing_count"], 8)
        self.assertEqual(data["tool_input"], {"topics": bad})   # the raw answer, not a summary

    def test_when_the_retry_does_not_improve_the_retry_is_saved(self):
        # 10 sections: 3 missing (30%) first, 5 missing (50%) on the retry - worse, yet not above the 50% failure gate that the
        # separate reduce_gate patch adds, so this test holds with or without that patch
        first = [{"topic_label_en": "a", "section_ids": list(range(1, 8))}]
        worse = [{"topic_label_en": "a", "section_ids": list(range(1, 6))}]
        self.reduce(FakeClient([fake_response(first), fake_response(worse, output_tokens=99)]))
        data = json.loads(self.rejected_file().read_text(encoding="utf-8"))
        self.assertEqual((data["rejected_attempt"], data["used_attempt"]), (2, 1))
        self.assertEqual(data["output_tokens"], 99)
        self.assertEqual(data["tool_input"], {"topics": worse})

    def test_a_tool_call_without_topics_is_recorded_as_such(self):
        out = self.reduce(FakeClient([fake_response(None), fake_response([{"topic_label_en": "a", "section_ids": list(range(1, 11))}])]))
        self.assertIn("topics returned=0", out)
        data = json.loads(self.rejected_file().read_text(encoding="utf-8"))
        self.assertEqual(data["topics_returned"], 0)

    def test_a_save_failure_never_fails_the_reduce(self):
        good = [{"topic_label_en": "a", "section_ids": list(range(1, 11))}]
        bad = [{"topic_label_en": "a", "section_ids": [1]}]
        with mock.patch.object(Path, "write_text", side_effect=OSError("disk full")):
            out = self.reduce(FakeClient([fake_response(bad), fake_response(good)]))
        self.assertIn("could not save the rejected attempt", out)

    def test_the_file_is_git_ignored(self):
        patterns = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("data/processed/review_flags/*.biweekly_reduce_rejected.json", patterns)

    def test_a_broken_diagnostics_record_never_fails_the_call(self):
        class Boom(list):
            def append(self, item):
                raise RuntimeError("diagnostics broke")
        good = [{"topic_label_en": "a", "section_ids": list(range(1, 11))}]
        with mock.patch.object(sb, "REDUCE_ATTEMPTS", Boom()):
            out = self.reduce(FakeClient([fake_response(good)]))
        self.assertIn("diagnostics skipped", out)
        self.assertIn("[reduce] -> 1 final topic(s)", out)   # the reduce itself completed with the same result


class PrefixSnippetFileTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def lines(self, n):
        return [f"[Topic {i}] \"before {i}\" -> \"after {i}\"" for i in range(n)]

    def test_daily_snippets_go_to_a_file_and_the_log_is_capped(self):
        syn.STAGE2_PREFIX_FIXES[:] = self.lines(13)
        self.addCleanup(syn.STAGE2_PREFIX_FIXES.clear)
        buf = io.StringIO()
        with mock.patch.object(syn, "REVIEW_FLAGS_DIR", self.dir), contextlib.redirect_stdout(buf):
            syn.print_prefix_fixes("2026-11-19")
        self.assertEqual(buf.getvalue().count("prefix hyphen fix ["), 10)
        self.assertIn("3 more in review_flags/2026-11-19.prefix_fixes.json", buf.getvalue())
        data = json.loads((self.dir / "2026-11-19.prefix_fixes.json").read_text(encoding="utf-8"))
        self.assertEqual(data["fixes"], self.lines(13))   # the file holds all of them

    def test_biweekly_snippets_go_to_a_file_named_for_the_period_end(self):
        sb.BIWEEKLY_PREFIX_FIXES[:] = self.lines(2)
        self.addCleanup(sb.BIWEEKLY_PREFIX_FIXES.clear)
        with mock.patch.object(sb, "REVIEW_FLAGS_DIR", self.dir), contextlib.redirect_stdout(io.StringIO()):
            sb.print_prefix_fixes("2026-11-18")
        data = json.loads((self.dir / "2026-11-18.biweekly_prefix_fixes.json").read_text(encoding="utf-8"))
        self.assertEqual(data["fixes"], self.lines(2))

    def test_no_repairs_means_no_file(self):
        syn.STAGE2_PREFIX_FIXES.clear()
        sb.BIWEEKLY_PREFIX_FIXES.clear()
        with mock.patch.object(syn, "REVIEW_FLAGS_DIR", self.dir), mock.patch.object(sb, "REVIEW_FLAGS_DIR", self.dir), \
                contextlib.redirect_stdout(io.StringIO()):
            syn.print_prefix_fixes("2026-11-19")
            sb.print_prefix_fixes("2026-11-18")
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_a_failed_save_never_raises(self):
        syn.STAGE2_PREFIX_FIXES[:] = self.lines(1)
        sb.BIWEEKLY_PREFIX_FIXES[:] = self.lines(1)
        self.addCleanup(syn.STAGE2_PREFIX_FIXES.clear)
        self.addCleanup(sb.BIWEEKLY_PREFIX_FIXES.clear)
        with mock.patch.object(syn, "REVIEW_FLAGS_DIR", self.dir), mock.patch.object(sb, "REVIEW_FLAGS_DIR", self.dir), \
                mock.patch.object(Path, "write_text", side_effect=OSError("disk full")), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            syn.print_prefix_fixes("2026-11-19")
            sb.print_prefix_fixes("2026-11-18")   # reaching this line is the assertion: nothing raised

    def test_a_broken_snippet_helper_does_not_stop_the_repair_itself(self):
        with mock.patch.object(syn, "attached_prefix_repairs", side_effect=RuntimeError("boom")):
            out = syn._finish_comparison({"topic_label_en": "T"}, {"comparison_text_he": GLUED})
        self.assertIn("ב-Süddeutsche", out["comparison_text_he"])   # the hyphen was still added
        with mock.patch.object(sb, "attached_prefix_repairs", side_effect=RuntimeError("boom")):
            result = sb._finish_biweekly_result({"topic_label_he": "נושא", "comparison_text_he": GLUED,
                                                 "comparison_text_en": "x", "comparison_text_de": "y"})
        self.assertIn("ב-Süddeutsche", result["comparison_text_he"])

    def test_the_new_files_are_really_ignored_by_git(self):
        """git itself decides (git check-ignore), not a text match on .gitignore. Skipped where git is not on the PATH."""
        import shutil
        import subprocess
        if shutil.which("git") is None:
            self.skipTest("git not available")
        names = ["2026-11-19.prefix_fixes.json", "2026-11-18.biweekly_prefix_fixes.json",
                 "2026-11-18.biweekly_reduce_rejected.json", "2026-11-19.stage2_rejected.json"]
        for name in names:
            r = subprocess.run(["git", "check-ignore", "-q", f"data/processed/review_flags/{name}"], cwd=PROJECT_ROOT)
            self.assertEqual(r.returncode, 0, f"{name} is not ignored by git")
        for name in ("2026-11-19.stage1.json", "2026-11-19.stage2_events.json"):   # these two ARE committed on purpose
            r = subprocess.run(["git", "check-ignore", "-q", f"data/processed/review_flags/{name}"], cwd=PROJECT_ROOT)
            self.assertEqual(r.returncode, 1, f"{name} should not be ignored")


if __name__ == "__main__":
    unittest.main()
