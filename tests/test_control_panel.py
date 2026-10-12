"""The control panel mirrors file names, task names and limits that actually
live in the two wrapper scripts. If either side changes alone, the panel
shows - or resets - something other than the state the wrapper acts on. These
tests only compare constants; no window is opened and nothing is read from
automation_state/."""
import importlib.machinery
import importlib.util
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import biweekly_autorun  # noqa: E402
import daily_autorun  # noqa: E402

_loader = importlib.machinery.SourceFileLoader("control_panel", str(PROJECT_ROOT / "scripts" / "automation_control_panel.pyw"))
panel = importlib.util.module_from_spec(importlib.util.spec_from_loader("control_panel", _loader))
_loader.exec_module(panel)


class DailyTabMirrorsDailyAutorunTest(unittest.TestCase):
    def test_same_files(self):
        self.assertEqual(panel.STATE_FILE, daily_autorun.STATE_FILE)
        self.assertEqual(panel.CONFIG_FILE, daily_autorun.CONFIG_FILE)
        self.assertEqual(panel.PAUSE_FLAG, daily_autorun.PAUSE_FLAG)
        self.assertEqual(panel.KILLSWITCH_FLAG, daily_autorun.KILLSWITCH_FLAG)

    def test_same_task_and_limit(self):
        self.assertEqual(panel.SCHEDULED_TASK_NAME, daily_autorun.SCHEDULED_TASK_NAME)
        self.assertEqual(panel.DAILY_FAILURE_LIMIT, daily_autorun.CONSECUTIVE_FAILURE_LIMIT)


class BiweeklyTabMirrorsBiweeklyAutorunTest(unittest.TestCase):
    def test_same_files(self):
        self.assertEqual(panel.BW_STATE_FILE, biweekly_autorun.STATE_FILE)
        self.assertEqual(panel.BW_KILLSWITCH_FLAG, biweekly_autorun.KILLSWITCH_FLAG)
        self.assertEqual(panel.BW_PAUSE_NEXT_FLAG, biweekly_autorun.PAUSE_NEXT_FLAG)

    def test_same_task_and_limit(self):
        self.assertEqual(panel.BW_TASK_NAME, biweekly_autorun.SCHEDULED_TASK_NAME)
        self.assertEqual(panel.BW_FAILURE_LIMIT, biweekly_autorun.CONSECUTIVE_FAILURE_LIMIT)

    def test_every_recordable_outcome_has_a_display_line(self):
        self.assertEqual(set(panel.BW_OUTCOME_TEXT), set(biweekly_autorun.OUTCOMES))

    def test_the_default_state_has_the_keys_the_panel_reads(self):
        self.assertEqual(set(panel.BW_DEFAULT_STATE), set(biweekly_autorun.DEFAULT_STATE))


class TabsShareNoStateTest(unittest.TestCase):
    def test_the_two_mechanisms_use_disjoint_files_and_tasks(self):
        daily = {panel.STATE_FILE, panel.CONFIG_FILE, panel.PAUSE_FLAG, panel.KILLSWITCH_FLAG}
        biweekly = {panel.BW_STATE_FILE, panel.BW_KILLSWITCH_FLAG, panel.BW_PAUSE_NEXT_FLAG}
        self.assertFalse(daily & biweekly)
        self.assertNotEqual(panel.SCHEDULED_TASK_NAME, panel.BW_TASK_NAME)


if __name__ == "__main__":
    unittest.main()
