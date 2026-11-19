"""The daily sanity gate (scripts/daily_autorun.py run_unittest_gate): the unchanged suite runs once more before the day is
declared failed, every attempt's duration is logged, and a suite that fails on both attempts still fails the day.

No subprocess, no API, no tracker.db: a fake runner stands in for run_step."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import daily_autorun  # noqa: E402
from daily_autorun import StepResult  # noqa: E402


class FakeRunner:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, log, name, args, timeout_key=None, kill_tree=False):
        self.calls.append((name, list(args), timeout_key, kill_tree))
        return self.results.pop(0)


def ok():
    return StepResult("unittest", True, 0, "", "Ran 5 tests\nOK")


def failed(code=1):
    return StepResult("unittest", False, code, "", "FAILED")


def timed_out():
    return StepResult("unittest", False, None, "", "", note="timed out after 600s")


class UnittestGateTest(unittest.TestCase):
    def setUp(self):
        self.lines = []
        self.log = self.lines.append

    def test_the_ceiling_is_ten_minutes_and_there_are_two_attempts(self):
        self.assertEqual(daily_autorun.TIMEOUTS["unittest"], 600)
        self.assertEqual(daily_autorun.UNITTEST_ATTEMPTS, 2)

    def test_a_green_first_attempt_runs_the_suite_once(self):
        runner = FakeRunner(ok())
        result = daily_autorun.run_unittest_gate(self.log, runner)
        self.assertTrue(result.ok)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(result.note, "")
        self.assertTrue(any("attempt 1/2: OK in " in line for line in self.lines))

    def test_the_suite_is_run_exactly_as_before(self):
        runner = FakeRunner(ok())
        daily_autorun.run_unittest_gate(self.log, runner)
        self.assertEqual(runner.calls, [("unittest", ["unittest", "discover", "-b", "-s", "tests"], "unittest", True)])

    def test_a_timeout_then_a_green_run_passes_with_a_note(self):
        runner = FakeRunner(timed_out(), ok())
        result = daily_autorun.run_unittest_gate(self.log, runner)
        self.assertTrue(result.ok)
        self.assertEqual(len(runner.calls), 2)
        self.assertIn("passed on attempt 2", result.note)
        self.assertIn("timed out after 600s", result.note)

    def test_a_failure_then_a_green_run_passes_with_a_note(self):
        result = daily_autorun.run_unittest_gate(self.log, FakeRunner(failed(), ok()))
        self.assertTrue(result.ok)
        self.assertIn("attempt 1 failed (exit 1)", result.note)

    def test_two_failures_still_fail_the_day(self):
        runner = FakeRunner(failed(), failed())
        result = daily_autorun.run_unittest_gate(self.log, runner)
        self.assertFalse(result.ok)
        self.assertEqual(len(runner.calls), 2)
        self.assertIn("failed on all 2 attempts", result.note)

    def test_two_timeouts_still_fail_the_day_and_there_is_no_third_attempt(self):
        runner = FakeRunner(timed_out(), timed_out())
        result = daily_autorun.run_unittest_gate(self.log, runner)
        self.assertFalse(result.ok)
        self.assertEqual(len(runner.calls), 2)
        self.assertIn("timed out after 600s", result.note)

    def test_every_attempt_logs_its_duration(self):
        daily_autorun.run_unittest_gate(self.log, FakeRunner(failed(), ok()))
        durations = [line for line in self.lines if "unittest attempt" in line and " in " in line and "s" in line]
        self.assertEqual(len([d for d in durations if "attempt 1/2: FAILED in" in d or "attempt 2/2: OK in" in d]), 2)


SPAWNER = (
    "import subprocess, sys, time" + chr(10)
    + "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])" + chr(10)
    + "open('child.pid', 'w').write(str(child.pid))" + chr(10)
    + "time.sleep(120)" + chr(10)
)


def pid_alive(pid):
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


@unittest.skipUnless(os.name == "nt", "the tree kill is the Windows taskkill path")
class ProcessTreeKillTest(unittest.TestCase):
    """A step that times out leaves no process behind: the child it started dies with it, before the next attempt."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        Path(self.tmp.name, "spawner.py").write_text(SPAWNER, encoding="utf-8")
        self.child_pid = None
        self.addCleanup(self._reap)

    def _reap(self):  # never leave the sleeping child behind, even when an assertion fails
        if self.child_pid and pid_alive(self.child_pid):
            subprocess.run(["taskkill", "/PID", str(self.child_pid), "/T", "/F"], capture_output=True)

    def _run_spawner(self, kill_tree):
        lines = []
        with mock.patch.object(daily_autorun, "PROJECT_ROOT", Path(self.tmp.name)),                 mock.patch.object(daily_autorun, "VENV_PYTHON", Path(sys.executable)),                 mock.patch.dict(daily_autorun.TIMEOUTS, {"spawner": 4}):
            result = daily_autorun.run_step(lines.append, "spawner", ["spawner"], timeout_key="spawner", kill_tree=kill_tree)
        pid_file = Path(self.tmp.name, "child.pid")
        self.child_pid = int(pid_file.read_text()) if pid_file.exists() else None
        return result, lines

    def test_with_kill_tree_the_child_of_a_timed_out_step_is_dead(self):
        result, lines = self._run_spawner(kill_tree=True)
        self.assertFalse(result.ok)
        self.assertIn("timed out", result.note)
        self.assertIsNotNone(self.child_pid)
        time.sleep(1)
        self.assertFalse(pid_alive(self.child_pid))
        self.assertTrue(any("process tree killed" in line for line in lines))

    def test_kill_process_tree_never_raises_on_a_missing_pid(self):
        daily_autorun.kill_process_tree(2 ** 22 + 12345)


if __name__ == "__main__":
    unittest.main()
