"""Hebrew terminology lines in the stage-2 writer prompts (daily and biweekly): the US "midterm elections" has one Hebrew term."""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.reporting import synthesize, synthesize_biweekly  # noqa: E402

TERM_LINE = 'the Hebrew term for the US "midterm elections" is "בחירות האמצע"'


class MidtermTermTest(unittest.TestCase):
    def test_the_daily_stage2_prompt_names_the_term(self):
        self.assertEqual(synthesize.STAGE2_SYSTEM_PROMPT.count(TERM_LINE), 1)

    def test_the_biweekly_stage2_prompt_names_the_term(self):
        self.assertEqual(synthesize_biweekly.BIWEEKLY_STAGE2_SYSTEM_PROMPT.count(TERM_LINE), 1)

    def test_the_overview_prompt_names_the_term_too(self):
        # "ארה"ב אחרי הבחירות בטרם המועד" came from the overview writer (19.11), so it needs the term as well.
        self.assertEqual(synthesize_biweekly.OVERVIEW_SYSTEM_PROMPT.count(TERM_LINE), 1)

    def test_the_stage1_grouping_prompt_is_not_touched(self):
        self.assertNotIn(TERM_LINE, synthesize.STAGE1_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
