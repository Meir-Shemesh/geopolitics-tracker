"""analyze.py with ANALYZE_USE_BATCH (Message Batches API, PROJECT_LOG 4.129), the analysis-mode columns and the summary query.

No API, no real database: the Anthropic client is a fake that implements just the batches calls the code uses, every
test works on a temporary SQLite file, and the regular-call fallback (analyze_page) is a spy.
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.analysis import analyze
from src.common import db

ROOT = Path(__file__).resolve().parents[1]
REAL_ANALYZE_PAGE = analyze.analyze_page  # captured at import, before any test replaces it with a spy


class Crash(BaseException):
    """Stands for the process dying during the wait: not an Exception, so nothing in the code can swallow it."""


def make_article(headline: str, countries=("US", "RU"), zones=()):
    return {
        "headline": headline, "author": "A. Writer", "region_topic": "Sanctions", "stance_summary": "Argues for caution.",
        "key_excerpt": "We should wait.", "country_codes": list(countries), "conflict_zones": list(zones),
    }


def answer_for(custom_id: str):
    file_id, page = analyze.parse_custom_id(custom_id)
    return [make_article(f"Headline {file_id}/{page}", ("US", "RU", "IL"))]


USAGE = dict(input_tokens=1000, output_tokens=200, cache_creation_input_tokens=0, cache_read_input_tokens=3900)


def tool_entry(custom_id, articles):
    content = [SimpleNamespace(type="tool_use", input={"articles": articles})]
    return SimpleNamespace(custom_id=custom_id, result=SimpleNamespace(
        type="succeeded", message=SimpleNamespace(content=content, usage=SimpleNamespace(**USAGE), stop_reason="tool_use")))


def other_entry(custom_id, kind):
    return SimpleNamespace(custom_id=custom_id, result=SimpleNamespace(type=kind, error=SimpleNamespace(message=kind)))


class FakeBatches:
    """client.messages.batches. `plan(custom_id)` -> a result entry, or None to leave the request unanswered unless
    it is canceled (then it comes back as canceled)."""

    def __init__(self, plan=None, behaviour="ok", db_path=None):
        self.plan = plan or (lambda cid: tool_entry(cid, answer_for(cid)))
        self.behaviour = behaviour  # ok | never_ends | crash | create_fails | results_fail
        self.created: list[tuple[str, list[dict]]] = []
        self.canceled: list[str] = []
        self.row_visible_at_first_poll: dict[str, bool] = {}
        self.db_path = db_path

    def create(self, requests):
        if self.behaviour == "create_fails":
            raise RuntimeError("503 overloaded")
        batch_id = f"msgbatch_{len(self.created) + 1}"
        self.created.append((batch_id, requests))
        return SimpleNamespace(id=batch_id)

    def retrieve(self, batch_id):
        if self.db_path and batch_id not in self.row_visible_at_first_poll:
            conn = sqlite3.connect(self.db_path)
            self.row_visible_at_first_poll[batch_id] = conn.execute(
                "SELECT 1 FROM api_batches WHERE batch_id = ?", (batch_id,)).fetchone() is not None
            conn.close()
        if self.behaviour == "crash":
            raise Crash()
        ended = self.behaviour in ("ok", "results_fail") or batch_id in self.canceled
        counts = SimpleNamespace(processing=0 if ended else 1, succeeded=0, errored=0, canceled=0, expired=0)
        return SimpleNamespace(processing_status="ended" if ended else "in_progress", request_counts=counts)

    def cancel(self, batch_id):
        self.canceled.append(batch_id)

    def results(self, batch_id):
        if self.behaviour == "results_fail":
            raise RuntimeError("results unavailable")
        out = []
        for request_id, requests in self.created:
            if request_id != batch_id:
                continue
            for request in requests:
                entry = self.plan(request["custom_id"])
                if entry is None and batch_id in self.canceled:
                    entry = other_entry(request["custom_id"], "canceled")
                if entry is not None:
                    out.append(entry)
        return out


class AnalyzeBatchTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)  # a simulated crash leaves run()'s connection open
        self.tmp = Path(self._tmp.name)
        self.db_path = self.tmp / "test.db"
        self.skip_path = self.tmp / "skip_files.txt"
        self.flag_dir = self.tmp / "review_flags"
        self.conn = self.connect()
        db.init_db(self.conn)
        self.regular_calls: list[str] = []
        self.fallback_plan = lambda ref: answer_for(f"a-{ref.split(':')[0]}-p{ref.split(':')[1]}")
        self.batches = FakeBatches(db_path=self.db_path)
        self.client = SimpleNamespace(messages=SimpleNamespace(batches=self.batches))

        def fake_analyze_page(client, newspaper, raw_text, is_letters_page_=False, ref=None):
            self.regular_calls.append(ref)
            result = self.fallback_plan(ref)
            if isinstance(result, Exception):
                raise result
            return result

        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("TRACKER_NO_USAGE_LOG", None)
        for p in (
            mock.patch.object(db, "DB_PATH", self.db_path),
            mock.patch.object(analyze, "get_connection", side_effect=self.connect),
            mock.patch.object(analyze, "analyze_page", side_effect=fake_analyze_page),
            mock.patch.object(analyze.anthropic, "Anthropic", side_effect=lambda: self.client),
            mock.patch.object(analyze, "load_dotenv"),
            mock.patch.object(analyze, "SKIP_FILES_PATH", self.skip_path),
            mock.patch.object(analyze, "FAILED_PAGES_DIR", self.flag_dir),
            mock.patch.object(analyze, "ANALYZE_BATCH_POLL_SECONDS", 0.005),
        ):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def add_file(self, message_id: int, pages: int = 3, newspaper: str = "Economist") -> int:
        cursor = self.conn.execute(
            "INSERT INTO downloaded_files (channel, message_id, file_name, newspaper, published_at, downloaded_at, "
            "local_path, report_date) VALUES ('t', ?, ?, ?, '2026-11-06T10:00:00+00:00', '2026-11-06T12:00:00+00:00', "
            "'/x.pdf', '2026-11-06')", (message_id, f"f{message_id}.pdf", newspaper))
        file_id = cursor.lastrowid
        for n in range(1, pages + 1):
            self.conn.execute(
                "INSERT INTO extracted_pages (file_id, page_number, raw_text, extracted_at) VALUES (?, ?, ?, 'x')",
                (file_id, n, f"page text {file_id}/{n}"))
            db.insert_page_screening(self.conn, file_id, n, True, "r", "2026-11-06T13:00:00+00:00", "m")
        self.conn.commit()
        return file_id

    def run_analyze(self, **kwargs) -> str:
        with mock.patch("builtins.print") as printed:
            analyze.run(**kwargs)
        return "\n".join(" ".join(str(a) for a in call.args) for call in printed.call_args_list)

    def query(self, sql, params=()):
        conn = self.connect()
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def page_states(self, file_id: int):
        return [(r["analysis_status"], r["analysis_mode"], r["analyzed_at"] is not None) for r in self.query(
            "SELECT analysis_status, analysis_mode, analyzed_at FROM page_screening WHERE file_id = ? ORDER BY page_number",
            (file_id,))]

    def usage_rows(self):
        return [tuple(r) for r in self.query("SELECT stage, ref FROM api_usage ORDER BY id")]


class BatchPathTest(AnalyzeBatchTestBase):
    def test_every_page_goes_out_in_one_batch_and_is_written_like_a_regular_answer(self):
        a, b = self.add_file(1, pages=3), self.add_file(2, pages=2)
        out = self.run_analyze()
        self.assertEqual(self.regular_calls, [])
        self.assertEqual(len(self.batches.created), 1)
        self.assertEqual(len(self.batches.created[0][1]), 5)
        self.assertEqual(self.page_states(a), [("completed", "batch", True)] * 3)
        self.assertEqual(self.page_states(b), [("completed", "batch", True)] * 2)
        self.assertEqual(self.query("SELECT COUNT(*) AS n FROM articles")[0]["n"], 5)
        self.assertEqual(self.query("SELECT COUNT(*) AS n FROM article_countries")[0]["n"], 15)
        self.assertIn("Batch: 1 submitted (5 request(s)), 0 resumed, 5 page(s) from batch, 0 regular-call fallback(s)", out)
        self.assertIn("Analysis: 5 page(s) analyzed, 0 page(s) failed, 5 article(s)", out)

    def test_the_batch_row_is_written_before_the_wait_and_closed_when_collected(self):
        self.add_file(1, pages=2)
        self.run_analyze()
        batch_id = self.batches.created[0][0]
        self.assertTrue(self.batches.row_visible_at_first_poll[batch_id])
        row = self.query("SELECT stage, n_requests, status, note FROM api_batches")[0]
        self.assertEqual((row["stage"], row["n_requests"], row["status"], row["note"]), ("analyze", 2, "collected", "ended"))

    def test_the_batch_request_is_exactly_the_regular_request(self):
        file_id = self.add_file(1, pages=1)
        self.run_analyze()
        request = self.batches.created[0][1][0]
        self.assertEqual(request["custom_id"], f"a-{file_id}-p1")
        self.assertEqual(request["params"], analyze.build_analyze_params("Economist", f"page text {file_id}/1", False))
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(usage=SimpleNamespace(input_tokens=1, output_tokens=1), content=[
                SimpleNamespace(type="tool_use", input={"articles": []})])

        fake = SimpleNamespace(messages=SimpleNamespace(create=create))
        with mock.patch.object(analyze, "record_api_usage"):
            REAL_ANALYZE_PAGE(fake, "Economist", f"page text {file_id}/1")  # the real function, not the setUp spy
        self.assertEqual(captured, request["params"])
        params = request["params"]
        self.assertEqual(params["model"], analyze.MODEL)
        self.assertEqual(params["thinking"], {"type": "adaptive"})
        self.assertEqual(params["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(params["tool_choice"], {"type": "tool", "name": "record_articles"})

    def test_a_letters_page_keeps_its_note_in_the_batch_request(self):
        file_id = self.add_file(1, pages=1)
        self.conn.execute("UPDATE extracted_pages SET raw_text = ? WHERE file_id = ?", ("LETTERS TO THE EDITOR\nDear Sir", file_id))
        self.conn.commit()
        self.run_analyze()
        content = self.batches.created[0][1][0]["params"]["messages"][0]["content"]
        self.assertIn("structurally identified as a Letters to the Editor page", content)

    def test_usage_is_logged_as_analyze_batch_at_half_price(self):
        self.add_file(1, pages=2)
        since = db.usage_marker()
        self.run_analyze()
        self.assertEqual([r[0] for r in self.usage_rows()], ["analyze_batch", "analyze_batch"])
        total = db.summarize_api_usage(since, "analyze", db_path=self.db_path)
        regular = 2 * db.estimate_cost_usd(analyze.MODEL, 1000, 200, 0, 3900)
        self.assertEqual(total["batch_calls"], 2)
        self.assertAlmostEqual(total["cost"], regular * 0.5, places=9)
        self.assertIn("batch: 2 of 2 calls at 50% price", db.format_usage_summary("analyze", total))

    def test_a_skip_listed_file_is_not_sent(self):
        a, b = self.add_file(1, pages=2), self.add_file(2, pages=2)
        self.skip_path.write_text(f"{b}\n", encoding="utf-8")
        self.run_analyze()
        ids = {r["custom_id"] for r in self.batches.created[0][1]}
        self.assertEqual(ids, {f"a-{a}-p1", f"a-{a}-p2"})
        self.assertEqual(self.page_states(b), [("pending", None, False)] * 2)

    def test_nothing_pending_means_no_batch(self):
        out = self.run_analyze()
        self.assertEqual(self.batches.created, [])
        self.assertNotIn("Batch:", out)


class FallbackTest(AnalyzeBatchTestBase):
    def test_one_errored_request_takes_a_regular_call_and_is_marked_sync(self):
        a = self.add_file(1, pages=3)
        bad = f"a-{a}-p2"
        self.batches.plan = lambda cid: other_entry(cid, "errored") if cid == bad else tool_entry(cid, answer_for(cid))
        out = self.run_analyze()
        self.assertEqual(self.regular_calls, [f"{a}:2"])
        self.assertEqual([s[1] for s in self.page_states(a)], ["batch", "sync", "batch"])
        self.assertEqual([s[0] for s in self.page_states(a)], ["completed"] * 3)
        self.assertIn("2 page(s) from batch, 1 regular-call fallback(s)", out)

    def test_an_expired_request_and_a_missing_result_both_fall_back(self):
        a = self.add_file(1, pages=3)
        plan = {f"a-{a}-p1": other_entry(f"a-{a}-p1", "expired"), f"a-{a}-p2": None}
        self.batches.plan = lambda cid: plan[cid] if cid in plan else tool_entry(cid, answer_for(cid))
        self.run_analyze()
        self.assertEqual(sorted(self.regular_calls), [f"{a}:1", f"{a}:2"])
        self.assertEqual([s[1] for s in self.page_states(a)], ["sync", "sync", "batch"])

    def test_a_malformed_batch_answer_falls_back_to_a_regular_call(self):
        a = self.add_file(1, pages=2)
        broken = {"headline": "no other keys"}
        self.batches.plan = lambda cid: tool_entry(cid, [broken]) if cid.endswith("p1") else tool_entry(cid, answer_for(cid))
        out = self.run_analyze()
        self.assertEqual(self.regular_calls, [f"{a}:1"])
        self.assertEqual([s[1] for s in self.page_states(a)], ["sync", "batch"])
        self.assertIn("unusable", out)

    def test_an_answer_without_an_articles_list_falls_back(self):
        a = self.add_file(1, pages=1)
        content = [SimpleNamespace(type="tool_use", input={"something": "else"})]
        self.batches.plan = lambda cid: SimpleNamespace(custom_id=cid, result=SimpleNamespace(
            type="succeeded", message=SimpleNamespace(content=content, usage=SimpleNamespace(**USAGE), stop_reason="tool_use")))
        self.run_analyze()
        self.assertEqual(self.regular_calls, [f"{a}:1"])
        self.assertEqual(self.page_states(a), [("completed", "sync", True)])

    def test_a_page_that_fails_in_the_batch_and_again_in_the_regular_call_is_a_failed_page(self):
        a = self.add_file(1, pages=2)
        self.batches.plan = lambda cid: other_entry(cid, "errored") if cid.endswith("p1") else tool_entry(cid, answer_for(cid))
        self.fallback_plan = lambda ref: RuntimeError("boom") if ref.endswith(":1") else answer_for("a-1-p2")
        out = self.run_analyze()
        self.assertEqual(self.page_states(a), [("pending", None, False), ("completed", "batch", True)])
        self.assertIn("Failed pages (1)", out)
        self.assertIn("RuntimeError: boom", out)

    def test_a_batch_that_cannot_be_created_sends_every_page_to_regular_calls(self):
        a = self.add_file(1, pages=3)
        self.batches.behaviour = "create_fails"
        out = self.run_analyze()
        self.assertEqual(len(self.regular_calls), 3)
        self.assertEqual([s[1] for s in self.page_states(a)], ["sync"] * 3)
        self.assertEqual(self.query("SELECT COUNT(*) AS n FROM api_batches")[0]["n"], 0)
        self.assertIn("batch phase failed", out)

    def test_a_batch_whose_results_cannot_be_read_is_abandoned_and_its_pages_fall_back(self):
        a = self.add_file(1, pages=3)
        self.batches.behaviour = "results_fail"
        out = self.run_analyze()
        self.assertEqual(len(self.regular_calls), 3)
        self.assertEqual([s[1] for s in self.page_states(a)], ["sync"] * 3)
        row = self.query("SELECT status, note FROM api_batches")[0]
        self.assertEqual(row["status"], "abandoned")
        self.assertIn("results unavailable", row["note"])
        self.assertIn("0 page(s) from batch, 3 regular-call fallback(s)", out)

    def test_a_batch_that_outlives_the_timeout_is_canceled_and_its_pages_fall_back(self):
        a = self.add_file(1, pages=3)
        self.batches.behaviour = "never_ends"
        self.batches.plan = lambda cid: None
        out = self.run_analyze(batch_timeout_seconds=0.05)
        batch_id = self.batches.created[0][0]
        self.assertEqual(self.batches.canceled, [batch_id])
        self.assertEqual(len(self.regular_calls), 3)
        self.assertEqual([s[1] for s in self.page_states(a)], ["sync"] * 3)
        row = self.query("SELECT status, note FROM api_batches")[0]
        self.assertEqual((row["status"], row["note"]), ("collected", "timeout, canceled"))
        self.assertIn("canceling", out)

    def test_the_timeout_constant_is_twenty_minutes_and_separate(self):
        self.assertEqual(analyze.ANALYZE_BATCH_TIMEOUT_SECONDS, 20 * 60)


class ResumeTest(AnalyzeBatchTestBase):
    def test_a_batch_left_open_by_a_dead_run_is_followed_not_submitted_again(self):
        a = self.add_file(1, pages=3)
        self.batches.behaviour = "crash"
        with self.assertRaises(Crash):
            self.run_analyze()
        row = self.query("SELECT batch_id, status, request_ids FROM api_batches")[0]
        self.assertEqual(row["status"], "submitted")
        self.assertEqual(sorted(json.loads(row["request_ids"])), [f"a-{a}-p1", f"a-{a}-p2", f"a-{a}-p3"])
        self.assertEqual(self.page_states(a), [("pending", None, False)] * 3)

        resumed = FakeBatches(db_path=self.db_path)
        resumed.created = list(self.batches.created)  # the batch the first run created still exists at the API
        self.client.messages.batches = resumed
        out = self.run_analyze()
        self.assertEqual(len(resumed.created), 1)  # nothing new was submitted
        self.assertEqual(self.regular_calls, [])
        self.assertEqual(self.page_states(a), [("completed", "batch", True)] * 3)
        self.assertIn("1 resumed", out)
        self.assertEqual(self.query("SELECT status FROM api_batches")[0]["status"], "collected")

    def test_only_pages_not_covered_by_the_open_batch_are_submitted(self):
        a = self.add_file(1, pages=2)
        self.batches.behaviour = "crash"
        with self.assertRaises(Crash):
            self.run_analyze()
        b = self.add_file(2, pages=2)  # arrived after the first run died
        resumed = FakeBatches(db_path=self.db_path)
        resumed.created = list(self.batches.created)
        self.client.messages.batches = resumed
        self.run_analyze()
        self.assertEqual(len(resumed.created), 2)
        self.assertEqual({r["custom_id"] for r in resumed.created[1][1]}, {f"a-{b}-p1", f"a-{b}-p2"})
        self.assertEqual(self.page_states(a), [("completed", "batch", True)] * 2)
        self.assertEqual(self.page_states(b), [("completed", "batch", True)] * 2)


class SwitchTest(AnalyzeBatchTestBase):
    def test_production_default_is_on_since_2026_11_07(self):
        self.assertTrue(analyze.ANALYZE_USE_BATCH, "flip to False (and commit) to roll back")

    def test_switch_off_nothing_touches_the_batches_api_and_pages_are_marked_sync(self):
        a = self.add_file(1, pages=2)
        self.batches.behaviour = "create_fails"
        with mock.patch.object(analyze, "ANALYZE_USE_BATCH", False):
            out = self.run_analyze()
        self.assertEqual(self.batches.created, [])
        self.assertEqual(len(self.regular_calls), 2)
        self.assertEqual(self.page_states(a), [("completed", "sync", True)] * 2)
        self.assertNotIn("Batch:", out)
        self.assertEqual(self.query("SELECT COUNT(*) AS n FROM api_batches")[0]["n"], 0)

    def test_the_explicit_argument_beats_the_constant_both_ways(self):
        self.add_file(1, pages=1)
        with mock.patch.object(analyze, "ANALYZE_USE_BATCH", True):
            self.run_analyze(use_batch=False)
        self.assertEqual(self.batches.created, [])
        self.add_file(2, pages=1)
        with mock.patch.object(analyze, "ANALYZE_USE_BATCH", False):
            self.run_analyze(use_batch=True)
        self.assertEqual(len(self.batches.created), 1)

    def test_the_command_line_has_batch_and_no_batch(self):
        result = subprocess.run([sys.executable, "-m", "src.analysis.analyze", "--help"], cwd=ROOT, capture_output=True,
                                text=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--batch", result.stdout)
        self.assertIn("--no-batch", result.stdout)
        self.assertIn("--batch-timeout-minutes", result.stdout)


class AnalysisModeColumnsTest(AnalyzeBatchTestBase):
    def test_init_db_adds_the_columns_to_an_old_table_and_old_rows_stay_empty(self):
        old = sqlite3.connect(self.tmp / "old.db")
        old.row_factory = sqlite3.Row
        old.executescript("""
            CREATE TABLE downloaded_files (id INTEGER PRIMARY KEY, channel TEXT NOT NULL DEFAULT 'c', message_id INTEGER,
                file_name TEXT, newspaper TEXT, published_at TEXT, downloaded_at TEXT, local_path TEXT);
            CREATE TABLE page_screening (id INTEGER PRIMARY KEY AUTOINCREMENT, file_id INTEGER NOT NULL,
                page_number INTEGER NOT NULL, is_relevant INTEGER NOT NULL, screening_reasoning TEXT NOT NULL,
                screened_at TEXT NOT NULL, model_used TEXT NOT NULL, analysis_status TEXT NOT NULL DEFAULT 'pending',
                UNIQUE(file_id, page_number));
            INSERT INTO page_screening (file_id, page_number, is_relevant, screening_reasoning, screened_at, model_used,
                analysis_status) VALUES (1, 1, 1, 'r', 'x', 'm', 'completed');
        """)
        old.commit()
        db.init_db(old)
        row = old.execute("SELECT analysis_status, analysis_mode, analyzed_at FROM page_screening").fetchone()
        self.assertEqual(tuple(row), ("completed", None, None))
        old.close()

    def test_the_summary_reads_a_database_that_has_not_been_migrated_yet_as_all_legacy(self):
        old = sqlite3.connect(self.tmp / "unmigrated.db")
        old.row_factory = sqlite3.Row
        old.executescript("""
            CREATE TABLE downloaded_files (id INTEGER PRIMARY KEY, report_date TEXT, published_at TEXT);
            CREATE TABLE page_screening (id INTEGER PRIMARY KEY, file_id INTEGER, page_number INTEGER,
                analysis_status TEXT NOT NULL DEFAULT 'pending');
            CREATE TABLE articles (id INTEGER PRIMARY KEY, file_id INTEGER, page_number INTEGER);
            CREATE TABLE article_countries (id INTEGER PRIMARY KEY, article_id INTEGER, country_code TEXT);
            INSERT INTO downloaded_files VALUES (1, '2026-11-06', '2026-11-06T10:00:00+00:00');
            INSERT INTO page_screening VALUES (1, 1, 1, 'completed');
            INSERT INTO articles VALUES (1, 1, 1);
            INSERT INTO article_countries VALUES (1, 1, 'US'), (2, 1, 'RU');
        """)
        rows = db.analysis_mode_summary(old)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["mode"], rows[0]["pages"], rows[0]["articles"], rows[0]["primary_tags"],
                          rows[0]["secondary_tags"]), (None, 1, 1, 1, 1))
        old.close()

    def test_set_analysis_status_without_a_mode_leaves_the_mode_untouched(self):
        a = self.add_file(1, pages=1)
        db.set_analysis_status(self.conn, a, 1, "completed", mode="batch", analyzed_at="2026-11-07T10:00:00+00:00")
        db.set_analysis_status(self.conn, a, 1, "skipped_duplicate")
        self.assertEqual(self.page_states(a), [("skipped_duplicate", "batch", True)])


class ModeSummaryTest(AnalyzeBatchTestBase):
    def add_article(self, file_id, page, countries):
        aid = db.insert_article(self.conn, file_id, page, "Economist", "en", f"h{file_id}{page}{countries}", "a", "t", "s",
                                "k", "2026-11-06T14:00:00+00:00")
        db.insert_article_countries(self.conn, aid, countries)
        return aid

    def test_pages_articles_and_primary_and_secondary_tags_per_date_and_mode(self):
        a = self.add_file(1, pages=3)
        for page, mode in ((1, "batch"), (2, "batch"), (3, None)):
            db.set_analysis_status(self.conn, a, page, "completed", mode=mode, analyzed_at="x" if mode else None)
        self.add_article(a, 1, ["US", "RU", "IL"])     # primary 1, secondary 2
        self.add_article(a, 2, ["US"])                  # primary 1, secondary 0
        self.add_article(a, 3, ["FR", "DE"])            # legacy page: primary 1, secondary 1
        self.add_article(a, 3, [])                      # no country at all
        rows = {(r["report_date"], r["mode"]): r for r in db.analysis_mode_summary(self.conn)}
        batch = rows[("2026-11-06", "batch")]
        self.assertEqual((batch["pages"], batch["articles"], batch["primary_tags"], batch["secondary_tags"]), (2, 2, 2, 2))
        self.assertEqual((batch["primary_per_article"], batch["secondary_per_article"], batch["tags_per_article"]),
                         (1.0, 1.0, 2.0))
        legacy = rows[("2026-11-06", None)]
        self.assertEqual((legacy["pages"], legacy["articles"], legacy["primary_tags"], legacy["secondary_tags"]), (1, 2, 1, 1))
        self.assertEqual(legacy["tags_per_article"], 1.0)

    def test_since_date_filters_and_newest_comes_first(self):
        a = self.add_file(1, pages=1)
        db.set_analysis_status(self.conn, a, 1, "completed", mode="sync", analyzed_at="x")
        self.conn.execute("UPDATE downloaded_files SET report_date = '2026-11-01' WHERE id = ?", (a,))
        b = self.add_file(2, pages=1)
        db.set_analysis_status(self.conn, b, 1, "completed", mode="batch", analyzed_at="x")
        self.conn.commit()
        rows = db.analysis_mode_summary(self.conn)
        self.assertEqual([(r["report_date"], r["mode"]) for r in rows], [("2026-11-06", "batch"), ("2026-11-01", "sync")])
        self.assertEqual([r["report_date"] for r in db.analysis_mode_summary(self.conn, since_date="2026-11-05")], ["2026-11-06"])

    def test_an_end_to_end_batch_run_shows_up_in_the_summary(self):
        self.add_file(1, pages=2)
        self.run_analyze()
        rows = db.analysis_mode_summary(self.connect())
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["mode"], rows[0]["pages"], rows[0]["articles"]), ("batch", 2, 2))
        self.assertEqual((rows[0]["primary_per_article"], rows[0]["secondary_per_article"]), (1.0, 2.0))


if __name__ == "__main__":
    unittest.main()
