"""The biweekly reduce summary table (biweekly_reduce_runs): what is recorded, and that recording never breaks a run.

No API, no tracker.db: a temporary database and a fake model client.
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tests"))

from src.common import db  # noqa: E402
from src.reporting import synthesize_biweekly as sb  # noqa: E402
from test_biweekly_reduce import FakeClient, fake_response, sections  # noqa: E402


class ReduceRunLogTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = Path(tmp.name) / "t.db"
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        db.init_db(conn)
        conn.close()
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("TRACKER_NO_USAGE_LOG", None)
        for target, kwargs in (("DB_PATH", {"new": self.db_path}),):
            p = mock.patch.object(db, target, **kwargs)
            p.start()
            self.addCleanup(p.stop)
        for name in ("count_tokens",):
            p = mock.patch.object(sb, name, return_value=1234)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(sb, "record_usage")
        p.start()
        self.addCleanup(p.stop)

    def rows(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute("SELECT * FROM biweekly_reduce_runs ORDER BY id")]
        finally:
            conn.close()

    def reduce(self, client, n=10):
        secs = sections(n)
        return sb.run_reduce(client, [("W1", [{"topic_label_en": "a", "section_ids": list(secs)}])], secs,
                             period=("2026-10-22", "2026-11-04"))

    def test_clean_run_records_counts_and_period(self):
        good = [{"topic_label_en": "a", "section_ids": list(range(1, 11))}]
        self.reduce(FakeClient([fake_response(good, output_tokens=777)]))
        (row,) = self.rows()
        self.assertEqual((row["start_date"], row["end_date"], row["outcome"]), ("2026-10-22", "2026-11-04", "ok"))
        self.assertEqual((row["input_sections"], row["input_groups"], row["final_topics"]), (10, 1, 1))
        self.assertEqual((row["missing_count"], row["duplicated_count"], row["retried"], row["retry_used"]), (0, 0, 0, 0))
        self.assertEqual((row["input_tokens"], row["output_tokens"], row["stop_reason"]), (100, 777, "tool_use"))
        self.assertEqual(row["retry_threshold"], sb.BIWEEKLY_GROUPING_RATIO_THRESHOLD)

    def test_retry_that_improves_is_recorded_as_used(self):
        bad = [{"topic_label_en": "a", "section_ids": list(range(1, 6))}]  # 5 missing of 10
        good = [{"topic_label_en": "a", "section_ids": list(range(1, 11))}]
        self.reduce(FakeClient([fake_response(bad), fake_response(good)]))
        (row,) = self.rows()
        self.assertEqual((row["retried"], row["retry_used"], row["missing_count"]), (1, 1, 0))
        self.assertEqual(row["input_tokens"], 200)  # both calls are billed

    def test_truncation_is_recorded_as_an_outcome(self):
        client = FakeClient([fake_response(None, stop_reason="max_tokens")])
        with self.assertRaises(sb.ReduceFailedError):
            self.reduce(client)
        (row,) = self.rows()
        self.assertEqual((row["outcome"], row["stop_reason"], row["final_topics"], row["retried"]), ("truncated", "max_tokens", 0, 0))

    def test_logging_failure_never_breaks_the_run(self):
        good = [{"topic_label_en": "a", "section_ids": list(range(1, 11))}]
        with mock.patch.object(db, "DB_PATH", Path(tempfile.gettempdir()) / "no_such_dir" / "x.db"):
            topics, _, _ = self.reduce(FakeClient([fake_response(good)]))
        self.assertEqual(len(topics), 1)

    def test_skipped_when_usage_logging_is_disabled(self):
        os.environ["TRACKER_NO_USAGE_LOG"] = "1"
        good = [{"topic_label_en": "a", "section_ids": list(range(1, 11))}]
        self.reduce(FakeClient([fake_response(good)]))
        self.assertEqual(self.rows(), [])

    def test_unknown_field_is_rejected_without_raising(self):
        db.record_biweekly_reduce_run(db_path=self.db_path, nonsense=1)
        self.assertEqual(self.rows(), [])


if __name__ == "__main__":
    unittest.main()
