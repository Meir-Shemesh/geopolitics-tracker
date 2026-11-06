"""Read-only: per report date and analysis mode (batch | sync | legacy = analyzed before the mode was recorded) - completed
pages, articles, and country tags per article split into primary (the first tag the model listed for an article) and
secondary (all the others). Built for the check of the batch-vs-regular difference in country tagging
(PROJECT_LOG 4.129). The same numbers come from db.analysis_mode_summary().

    python -m scripts.analysis_mode_report [--days 14] [--db path/to/tracker.db]
"""

import argparse
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from src.common import db

sys.stdout.reconfigure(encoding="utf-8")


def format_rows(rows: list[dict]) -> str:
    header = f"{'report date':<12} {'mode':<7} {'pages':>6} {'articles':>9} {'primary/art':>12} {'secondary/art':>14} {'tags/art':>9}"
    lines = [header, "-" * len(header)]
    for r in rows:
        def fmt(v):
            return "-" if v is None else f"{v:.3f}"
        lines.append(f"{r['report_date'] or '?':<12} {r['mode'] or 'legacy':<7} {r['pages']:>6} {r['articles']:>9} "
                     f"{fmt(r['primary_per_article']):>12} {fmt(r['secondary_per_article']):>14} {fmt(r['tags_per_article']):>9}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analysis mode (batch/sync) and country tags per article, per report date.")
    parser.add_argument("--days", type=int, default=14, help="How many days back (default 14).")
    parser.add_argument("--db", type=Path, default=None, help="A database file (default: the project's tracker.db).")
    args = parser.parse_args()
    path = args.db or db.DB_PATH
    conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    try:
        since = (date.today() - timedelta(days=args.days)).isoformat()
        print(format_rows(db.analysis_mode_summary(conn, since_date=since)))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
