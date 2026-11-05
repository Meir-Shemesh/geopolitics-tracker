"""screen.py with SCREEN_USE_BATCH (Message Batches API), and the switch OFF.

No API, no real database: the Anthropic client is a fake that implements just the batches calls the code uses, and
every test works on a temporary SQLite file. The fallback path (screen_page) is a spy.
"""

import json
import os
import re
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.analysis import screen
from src.common import batch_runner, db

SANCTIONS = "The prime minister said on Thursday that the sanctions on the northern ports would stay in place. "
SPORTS = "The striker scored twice in the second half as the home side won the league match by three goals. "


def page_text(kind: str, n: int) -> str:
    """Unique text per page (>200 chars), relevant to the fake model if it mentions sanctions."""
    return (SANCTIONS if kind == "rel" else SPORTS) * 3 + f" Page marker {n}."


def fake_verdict(text: str) -> tuple[bool, str]:
    return ("sanctions" in text), ("about sanctions" if "sanctions" in text else "sports page")


class Crash(BaseException):
    """Stands for the process dying during the wait: not an Exception, so nothing in the code can swallow it."""


def tool_entry(custom_id, is_relevant, reasoning, tool=True):
    content = [SimpleNamespace(type="tool_use", input={"is_relevant": is_relevant, "reasoning": reasoning})] if tool else \
        [SimpleNamespace(type="text", text="refused")]
    usage = SimpleNamespace(input_tokens=1000, output_tokens=80, cache_creation_input_tokens=0, cache_read_input_tokens=0)
    return SimpleNamespace(custom_id=custom_id, result=SimpleNamespace(
        type="succeeded", message=SimpleNamespace(content=content, usage=usage, stop_reason="tool_use" if tool else "refusal")))


def other_entry(custom_id, kind):
    return SimpleNamespace(custom_id=custom_id, result=SimpleNamespace(type=kind, error=SimpleNamespace(message=kind)))


class FakeBatches:
    """client.messages.batches. `plan(custom_id, text)` -> a result entry, or None to leave the request unanswered
    unless it is canceled (then it comes back as canceled)."""

    def __init__(self, plan=None, behaviour="ok", db_path=None):
        self.plan = plan or (lambda cid, text: tool_entry(cid, *fake_verdict(text)))
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

    def _requests(self, batch_id):
        return dict(self.created)[batch_id]

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
        for request in self._requests(batch_id):
            text = request["params"]["messages"][0]["content"]
            entry = self.plan(request["custom_id"], text)
            if entry is None:
                entry = other_entry(request["custom_id"], "canceled") if batch_id in self.canceled else None
            if entry is not None:
                out.append(entry)
        return out


class ScreenBatchTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)  # a simulated crash leaves run()'s connection open
        self.tmp = Path(self._tmp.name)
        self.db_path = self.tmp / "test.db"
        self.conn = self.connect()
        db.init_db(self.conn)
        self.api_calls: list[str] = []
        self.claim_calls: list[dict] = []
        self.batches = FakeBatches(db_path=self.db_path)
        self.client = SimpleNamespace(messages=SimpleNamespace(batches=self.batches))
        self.claim_tz = None

        def fake_screen_page(client, raw_text, model=None, ref=None):
            self.api_calls.append(ref)
            return fake_verdict(raw_text)

        real_claim = db.claim_report_date_on_first_scan

        def spy_claim(conn, file_id, **kwargs):
            self.claim_calls.append(kwargs)
            return real_claim(conn, file_id, **kwargs, **({"tz": self.claim_tz} if self.claim_tz else {}))

        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("TRACKER_NO_USAGE_LOG", None)
        for p in (
            mock.patch.object(db, "DB_PATH", self.db_path),
            mock.patch.object(screen, "get_connection", side_effect=self.connect),
            mock.patch.object(screen, "screen_page", side_effect=fake_screen_page),
            mock.patch.object(screen, "claim_report_date_on_first_scan", side_effect=spy_claim),
            mock.patch.object(screen.anthropic, "Anthropic", side_effect=lambda: self.client),
            mock.patch.object(screen, "load_dotenv"),
            mock.patch.object(screen, "SCREEN_BATCH_POLL_SECONDS", 0.005),
        ):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def add_file(self, newspaper="Guardian", message_id=None, local_path="/missing.pdf", report_date="2026-11-04") -> int:
        message_id = message_id or (self.conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM downloaded_files").fetchone()[0])
        cursor = self.conn.execute(
            "INSERT INTO downloaded_files (channel, message_id, file_name, newspaper, published_at, downloaded_at, "
            "local_path, report_date) VALUES ('t', ?, ?, ?, '2026-11-04T08:00:00+00:00', '2026-11-04T12:00:00+00:00', ?, ?)",
            (message_id, f"f{message_id}.pdf", newspaper, local_path, report_date))
        self.conn.commit()
        return cursor.lastrowid

    def add_page(self, file_id: int, number: int, text: str) -> None:
        self.conn.execute("INSERT INTO extracted_pages (file_id, page_number, raw_text, extracted_at) VALUES (?, ?, ?, 'x')",
                          (file_id, number, text))
        self.conn.commit()

    def seed_four_pages(self) -> int:
        fid = self.add_file()
        for n, kind in enumerate(("rel", "sports", "rel", "sports"), 1):
            self.add_page(fid, n, page_text(kind, n))
        return fid

    def rows(self) -> list[tuple]:
        conn = self.connect()
        try:
            return [tuple(r) for r in conn.execute(
                "SELECT file_id, page_number, is_relevant, screening_reasoning, model_used, analysis_status "
                "FROM page_screening ORDER BY file_id, page_number")]
        finally:
            conn.close()

    def usage_rows(self) -> list[sqlite3.Row]:
        conn = self.connect()
        try:
            return conn.execute("SELECT stage, model, input_tokens, output_tokens, ref FROM api_usage ORDER BY id").fetchall()
        finally:
            conn.close()

    def batch_rows(self) -> list[sqlite3.Row]:
        conn = self.connect()
        try:
            return conn.execute("SELECT * FROM api_batches ORDER BY id").fetchall()
        finally:
            conn.close()

    def run_screen(self, **kwargs) -> str:
        with mock.patch("builtins.print") as printed:
            screen.run(**kwargs)
        return "\n".join(str(c.args[0]) for c in printed.call_args_list if c.args)


class SwitchOffTest(ScreenBatchTestBase):
    def test_default_is_off_and_nothing_touches_the_batches_api(self):
        self.assertFalse(screen.SCREEN_USE_BATCH)
        self.seed_four_pages()
        self.batches.create = mock.Mock(side_effect=AssertionError("batches API used with the switch off"))
        out = self.run_screen()
        self.assertEqual(len(self.api_calls), 4)
        self.assertEqual(self.batch_rows(), [])
        self.assertNotIn("batch", out.lower())
        self.assertEqual(self.claim_calls, [{}], "with the switch off claim_report_date is called exactly as before")

    def test_switch_off_and_on_write_identical_verdict_rows(self):
        self.seed_four_pages()
        self.run_screen()
        off_rows = self.rows()
        self.conn.execute("DELETE FROM page_screening")
        self.conn.commit()
        self.run_screen(use_batch=True)
        self.assertEqual(self.rows(), off_rows)


class BatchSuccessTest(ScreenBatchTestBase):
    def test_full_success_uses_one_batch_and_no_regular_call(self):
        self.seed_four_pages()
        out = self.run_screen(use_batch=True)
        self.assertEqual(self.api_calls, [])
        self.assertEqual(len(self.batches.created), 1)
        _, requests = self.batches.created[0]
        self.assertEqual([r["custom_id"] for r in requests], ["s-1-p1", "s-1-p2", "s-1-p3", "s-1-p4"])
        for r in requests:
            self.assertEqual(r["params"], screen.build_screen_params(r["params"]["messages"][0]["content"]))
            self.assertRegex(r["custom_id"], r"^[a-zA-Z0-9_-]{1,64}$")
        self.assertEqual([(r[2], r[4]) for r in self.rows()], [(1, screen.MODEL), (0, screen.MODEL), (1, screen.MODEL), (0, screen.MODEL)])
        self.assertIn("batch: 1 submitted (4 request(s))", out)
        self.assertIn("4 page(s) from batch, 0 regular-call fallback(s)", out)

    def test_batch_id_is_stored_before_the_wait_starts(self):
        self.seed_four_pages()
        self.run_screen(use_batch=True)
        self.assertEqual(self.batches.row_visible_at_first_poll, {"msgbatch_1": True})
        (row,) = self.batch_rows()
        self.assertEqual((row["batch_id"], row["stage"], row["status"], row["n_requests"]), ("msgbatch_1", "screen", "collected", 4))

    def test_no_pages_needing_the_api_means_no_batch(self):
        fid = self.add_file()
        self.add_page(fid, 1, "   ")  # empty page: recorded without the API
        self.run_screen(use_batch=True)
        self.assertEqual(self.batches.created, [])
        self.assertEqual(self.batch_rows(), [])
        self.assertEqual(len(self.rows()), 1)

    def test_chunking_respects_both_limits(self):
        reqs = [{"custom_id": f"s-1-p{i}", "params": {"x": "y" * 100}} for i in range(10)]
        self.assertEqual([len(c) for c in batch_runner.split_into_batches(reqs, max_requests=4)], [4, 4, 2])
        size = batch_runner.estimate_request_bytes(reqs[0])
        self.assertEqual([len(c) for c in batch_runner.split_into_batches(reqs, max_bytes=size * 3)], [3, 3, 3, 1])
        self.assertEqual(batch_runner.split_into_batches([]), [])
        with mock.patch.object(batch_runner, "MAX_REQUESTS_PER_BATCH", 2):  # the pipeline path honours the limit too
            self.seed_four_pages()
            self.run_screen(use_batch=True)
        self.assertEqual([len(r) for _, r in self.batches.created], [2, 2])

    def test_custom_id_round_trip(self):
        for fid, pn in ((1, 1), (999999, 12345)):
            self.assertEqual(screen.parse_custom_id(screen.batch_custom_id(fid, pn)), (fid, pn))
        self.assertIsNone(screen.parse_custom_id("nonsense"))


class PartialFailureTest(ScreenBatchTestBase):
    def test_failed_requests_fall_back_once_each_and_nothing_is_written_twice(self):
        fid = self.seed_four_pages()

        def plan(cid, text):
            return {"s-1-p1": tool_entry(cid, *fake_verdict(text)),
                    "s-1-p2": other_entry(cid, "errored"),
                    "s-1-p3": other_entry(cid, "expired"),
                    "s-1-p4": tool_entry(cid, True, "", tool=False)}[cid]
        self.batches.plan = plan
        out = self.run_screen(use_batch=True)
        self.assertEqual(self.api_calls, [f"{fid}:2", f"{fid}:3", f"{fid}:4"])
        self.assertEqual(len(self.rows()), 4)
        self.assertEqual([r[2] for r in self.rows()], [1, 0, 1, 0])  # verdicts of the fallback calls, not the empty one
        self.assertIn("1 page(s) from batch, 3 regular-call fallback(s)", out)
        # the succeeded-but-unusable request was billed, so it is logged; errored/expired ones were not
        self.assertEqual([u["ref"] for u in self.usage_rows()], [f"{fid}:1", f"{fid}:4"])

    def test_malformed_verdict_is_treated_as_missing(self):
        self.seed_four_pages()
        self.batches.plan = lambda cid, text: tool_entry(cid, "yes", None) if cid == "s-1-p2" else tool_entry(cid, *fake_verdict(text))
        self.run_screen(use_batch=True)
        self.assertEqual(len(self.api_calls), 1)
        self.assertEqual(len(self.rows()), 4)


class TimeoutAndFallbackTest(ScreenBatchTestBase):
    def test_timeout_cancels_and_only_unanswered_pages_use_regular_calls(self):
        fid = self.seed_four_pages()
        self.batches.behaviour = "never_ends"
        self.batches.plan = lambda cid, text: tool_entry(cid, *fake_verdict(text)) if cid in ("s-1-p1", "s-1-p2") else None
        out = self.run_screen(use_batch=True, batch_timeout_seconds=0.03)
        self.assertEqual(self.batches.canceled, ["msgbatch_1"])
        self.assertEqual(self.api_calls, [f"{fid}:3", f"{fid}:4"])
        self.assertEqual(len(self.rows()), 4)
        (row,) = self.batch_rows()
        self.assertEqual((row["status"], row["note"]), ("collected", "timeout, canceled"))
        self.assertIn("canceling", out)

    def test_batch_creation_failure_falls_back_for_every_page(self):
        self.seed_four_pages()
        self.batches.behaviour = "create_fails"
        out = self.run_screen(use_batch=True)
        self.assertEqual(len(self.api_calls), 4)
        self.assertEqual(len(self.rows()), 4)
        self.assertEqual(self.batch_rows(), [])
        self.assertIn("batch phase failed", out)

    def test_unreadable_results_abandon_the_batch_and_fall_back(self):
        self.seed_four_pages()
        self.batches.behaviour = "results_fail"
        self.run_screen(use_batch=True)
        self.assertEqual(len(self.api_calls), 4)
        self.assertEqual(len(self.rows()), 4)
        (row,) = self.batch_rows()
        self.assertEqual(row["status"], "abandoned")


class CrashAndResumeTest(ScreenBatchTestBase):
    def test_second_run_follows_the_same_batch_instead_of_submitting_again(self):
        fid = self.seed_four_pages()
        self.batches.behaviour = "crash"
        with self.assertRaises(Crash):
            self.run_screen(use_batch=True)
        (row,) = self.batch_rows()
        self.assertEqual((row["status"], row["n_requests"]), ("submitted", 4))
        self.assertEqual(self.rows(), [])
        self.assertEqual(len(self.batches.created), 1)

        self.batches.behaviour = "ok"  # the batch finished while the computer was down
        out = self.run_screen(use_batch=True)
        self.assertEqual(len(self.batches.created), 1, "must not submit (and pay for) the same pages again")
        self.assertEqual(self.api_calls, [])
        self.assertEqual(len(self.rows()), 4)
        self.assertEqual(self.batch_rows()[0]["status"], "collected")
        self.assertIn("following msgbatch_1 left open by an earlier run", out)
        self.assertEqual(len(self.usage_rows()), 4)

    def test_resumed_batch_that_is_too_old_is_canceled_and_its_pages_are_not_resubmitted(self):
        self.seed_four_pages()
        self.batches.behaviour = "crash"
        with self.assertRaises(Crash):
            self.run_screen(use_batch=True)
        self.batches.behaviour = "never_ends"
        self.batches.plan = lambda cid, text: tool_entry(cid, *fake_verdict(text)) if cid == "s-1-p1" else None
        self.run_screen(use_batch=True, batch_timeout_seconds=0.0)
        self.assertEqual(self.batches.canceled, ["msgbatch_1"])
        self.assertEqual(len(self.batches.created), 1, "pages of the old batch go to regular calls, not into a new batch")
        self.assertEqual(len(self.api_calls), 3)
        self.assertEqual(len(self.rows()), 4)

    def test_nothing_is_written_when_the_run_dies(self):
        self.seed_four_pages()
        self.batches.behaviour = "crash"
        with self.assertRaises(Crash):
            self.run_screen(use_batch=True)
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.api_calls, [])


class MidnightTest(ScreenBatchTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.claim_tz = timezone.utc
        self.t_start = datetime(2026, 11, 4, 21, 50, tzinfo=timezone.utc)
        self.t_late = datetime(2026, 11, 5, 4, 50, tzinfo=timezone.utc)  # the batch "finishes" the next morning, past the 03:00 cutoff
        calls = []
        test = self

        class ClockedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                calls.append(1)
                moment = test.t_start if len(calls) == 1 else test.t_late
                return moment if tz is None else moment.astimezone(tz)

        p = mock.patch.object(screen, "datetime", ClockedDatetime)
        p.start()
        self.addCleanup(p.stop)

    def report_date(self, fid):
        conn = self.connect()
        try:
            return tuple(conn.execute("SELECT report_date, report_date_original FROM downloaded_files WHERE id = ?", (fid,)).fetchone())
        finally:
            conn.close()

    def test_report_date_follows_the_start_of_the_run_not_the_end_of_the_batch(self):
        fid = self.seed_four_pages()
        self.run_screen(use_batch=True)
        self.assertEqual(self.claim_calls, [{"now": self.t_start.isoformat()}])
        self.assertEqual(self.report_date(fid), ("2026-11-04", None), "a batch ending after midnight must not shift the date")

    def test_same_fixture_would_shift_if_the_claim_used_the_late_moment(self):
        # the guard is real: claiming with the post-midnight moment does move the file to the next day
        fid = self.seed_four_pages()
        moved = db.claim_report_date_on_first_scan(self.conn, fid, now=self.t_late.isoformat(), tz=timezone.utc)
        self.assertEqual(moved["new"], "2026-11-05")


class DuplicatesTest(ScreenBatchTestBase):
    def seed_mixed(self):
        """Archive dup, in-run text dup, empty page, byte-identical duplicate file, and 2 genuinely new pages."""
        old = self.add_file("Guardian")
        self.add_page(old, 1, page_text("rel", 100))
        conn = self.connect()
        conn.execute("INSERT INTO page_screening (file_id, page_number, is_relevant, screening_reasoning, screened_at, model_used) "
                     "VALUES (?, 1, 1, 'old', 'x', 'm')", (old,))
        conn.commit(); conn.close()
        screen.ensure_text_hashes(self.conn)
        a = self.tmp / "a.pdf"; b = self.tmp / "b.pdf"
        a.write_bytes(b"same-bytes"); b.write_bytes(b"same-bytes")
        f1 = self.add_file("Guardian", local_path=str(a))
        f2 = self.add_file("Guardian", local_path=str(b))
        self.add_page(f1, 1, page_text("rel", 100))        # text equals the archive page -> copy
        self.add_page(f1, 2, page_text("rel", 201))        # new
        self.add_page(f1, 3, page_text("sports", 202))     # new
        self.add_page(f1, 4, "")                           # empty
        self.add_page(f1, 5, page_text("rel", 203))        # new ...
        self.add_page(f1, 6, page_text("rel", 203))        # ... and an in-run text duplicate of it
        for n in (1, 2, 3, 4, 5, 6):                       # f2 is a byte-identical copy of f1
            self.add_page(f2, n, page_text("rel", 100) if n == 1 else "")
        return f1, f2

    def test_duplicates_empty_pages_and_copies_never_reach_the_batch(self):
        f1, f2 = self.seed_mixed()
        self.run_screen(use_batch=True)
        (_, requests), = self.batches.created
        self.assertEqual(sorted(r["custom_id"] for r in requests), sorted(f"s-{f1}-p{n}" for n in (2, 3, 5)))

    def test_batch_sends_exactly_the_pages_the_regular_path_calls_the_api_for(self):
        f1, f2 = self.seed_mixed()
        self.run_screen()  # switch off: record which pages the loop sends to the API
        regular = sorted(self.api_calls)
        self.conn.execute("DELETE FROM page_screening WHERE screened_at != 'x'")
        self.conn.commit()
        self.api_calls.clear()
        self.run_screen(use_batch=True)
        (_, requests), = self.batches.created
        sent = sorted(f"{parse[0]}:{parse[1]}" for parse in (screen.parse_custom_id(r["custom_id"]) for r in requests))
        self.assertEqual(sent, regular)
        self.assertEqual(self.api_calls, [], "no page that was sent to the batch is also sent as a regular call")


class CostTest(ScreenBatchTestBase):
    def test_batch_calls_are_logged_once_and_priced_at_half(self):
        self.seed_four_pages()
        started = db.usage_marker()
        self.run_screen(use_batch=True)
        rows = self.usage_rows()
        self.assertEqual([(r["stage"], r["model"]) for r in rows], [("screen_batch", screen.MODEL)] * 4)
        total = db.summarize_api_usage(started, "screen")
        standard = db.estimate_cost_usd(screen.MODEL, 1000, 80, 0, 0)
        self.assertAlmostEqual(total["cost"], 4 * standard * 0.5)
        self.assertEqual(total["batch_calls"], 4)
        line = db.format_usage_summary("screen", total)
        self.assertIn("batch: 4 of 4 calls at 50% price", line)
        self.assertIn("est. $0.00", line)

    def test_mixed_batch_and_regular_calls_each_priced_by_their_own_stage(self):
        db.record_api_usage("screen", screen.MODEL, SimpleNamespace(input_tokens=1000, output_tokens=80))
        db.record_api_usage("screen_batch", screen.MODEL, SimpleNamespace(input_tokens=1000, output_tokens=80))
        total = db.summarize_api_usage("1970-01-01T00:00:00+00:00", "screen")
        standard = db.estimate_cost_usd(screen.MODEL, 1000, 80, 0, 0)
        self.assertAlmostEqual(total["cost"], standard * 1.5)
        self.assertEqual((total["calls"], total["batch_calls"]), (2, 1))

    def test_usage_report_prices_batch_stage_at_half(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from scripts import usage_report
        full = usage_report.cost_usd(screen.MODEL, 1000, 80, 0, 0, stage="screen")
        half = usage_report.cost_usd(screen.MODEL, 1000, 80, 0, 0, stage="screen_batch")
        self.assertAlmostEqual(half, full / 2)
        self.assertEqual(usage_report.cost_usd(screen.MODEL, 1000, 80, 0, 0), full)  # old call signature unchanged

    def test_summary_without_batch_calls_is_unchanged(self):
        db.record_api_usage("screen", screen.MODEL, SimpleNamespace(input_tokens=1000, output_tokens=80))
        line = db.format_usage_summary("screen", db.summarize_api_usage("1970-01-01T00:00:00+00:00", "screen"))
        self.assertNotIn("batch", line)


if __name__ == "__main__":
    unittest.main()
