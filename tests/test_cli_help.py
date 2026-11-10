"""Every module daily_autorun launches must start from its real command line.

2026-11-10: the daily run crashed twice at `python -m src.reporting.synthesize` because a '%' in an argparse help string
raises when the parser is built (Python 3.14 checks help at add_argument time). The unit tests called run() directly,
so nothing exercised the parser. `--help` builds every argument, so it fails the same way, without doing any work."""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Modules with an argparse CLI: --help is safe (argparse prints and exits before any work).
HELP_MODULES = [
    "src.extraction.extract",
    "src.analysis.screen",
    "src.analysis.analyze",
    "src.reporting.synthesize",
    "src.reporting.render",
    "scripts.pdf_health_check",
]
# Modules launched by daily_autorun WITHOUT a parser: --help would run them for real (fetch talks to Telegram, publish
# rebuilds docs/), so they are only imported. If one gains a parser, move it to HELP_MODULES (the test below fails first).
IMPORT_ONLY_MODULES = [
    "src.ingestion.fetch",
    "scripts.orphan_review",
    "src.publishing.publish",
]


def _run(args):
    return subprocess.run([sys.executable, *args], cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)


class CliHelpTests(unittest.TestCase):
    def test_help_exits_zero(self):
        for module in HELP_MODULES:
            with self.subTest(module=module):
                result = _run(["-m", module, "--help"])
                self.assertEqual(result.returncode, 0, f"{module} --help failed:\n{result.stderr[-600:]}")
                self.assertIn("usage", result.stdout.lower())

    def test_import_only_modules_import_and_have_no_parser(self):
        for module in IMPORT_ONLY_MODULES:
            with self.subTest(module=module):
                result = _run(["-c", f"import {module}"])
                self.assertEqual(result.returncode, 0, f"import {module} failed:\n{result.stderr[-600:]}")
                path = ROOT / (module.replace(".", "/") + ".py")
                self.assertNotIn("ArgumentParser", path.read_text(encoding="utf-8"),
                                 f"{module} now has an argparse parser: move it to HELP_MODULES")

    def test_every_daily_autorun_module_is_covered(self):
        """A step added to daily_autorun without a CLI check here must fail this test."""
        source = (ROOT / "scripts" / "daily_autorun.py").read_text(encoding="utf-8")
        import re
        launched = set(re.findall(r'run_step\(log, "[a-z_0-9]+", \["((?:src|scripts)\.[a-z_.]+)"', source))
        covered = set(HELP_MODULES) | set(IMPORT_ONLY_MODULES)
        self.assertEqual(launched - covered, set(), "daily_autorun launches a module with no CLI check")


class SynthesizeParserTests(unittest.TestCase):
    def test_parser_builds_with_batch_flags(self):
        from src.reporting import synthesize
        parser = synthesize.build_parser()
        args = parser.parse_args(["--date", "2026-11-10", "--batch", "--batch-timeout", "7", "--dry-run"])
        self.assertTrue(args.batch)
        self.assertEqual(args.batch_timeout, 7)
        self.assertTrue(args.dry_run)
        self.assertFalse(parser.parse_args(["--date", "2026-11-10", "--no-batch"]).batch)
        self.assertIsNone(parser.parse_args(["--date", "2026-11-10"]).batch)

    def test_no_unescaped_percent_in_help_strings(self):
        """Any parser in the project: a bare '%' in help raises at build time on Python 3.14."""
        import re
        for path in list((ROOT / "src").rglob("*.py")) + list((ROOT / "scripts").glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"help=(?:\(|f?\")(.*)", text):
                line = match.group(1)
                stripped = line.replace("%%", "")
                self.assertNotIn("%", stripped, f"{path.name}: unescaped % in a help string: {line[:80]}")


if __name__ == "__main__":
    unittest.main()
