"""Read-only audit of the text already stored in report_sections (PROJECT_LOG 4.102/4.103).

Runs the same checks synthesize.py now applies before writing - foreign-script characters in any
field, a digit 1 wedged between Latin names, and a newspaper count in the prose that exceeds the
newspapers of the section's own articles - over every report (or those from --since on), and prints
the number of flags per date. Use it to see whether the leak rate keeps rising after the 2026-10-19
guard: dates from 2026-10-20 on were produced WITH the guard, so flags there mean it is not enough.

    python -m scripts.audit_report_text                  # whole archive
    python -m scripts.audit_report_text --since 2026-10-20 -v
"""
import argparse
import collections
import sys

from src.common.db import get_connection
from src.reporting import synthesize as syn

sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--since", default="0000-00-00", help="first report date to include (YYYY-MM-DD)")
    parser.add_argument("-v", "--verbose", action="store_true", help="print every flag, not just the per-date counts")
    args = parser.parse_args()

    conn = get_connection()
    articles = [{"id": r["id"], "newspaper": r["newspaper"]} for r in conn.execute("SELECT id, newspaper FROM articles")]
    links = collections.defaultdict(list)
    for r in conn.execute("SELECT section_id, article_id FROM report_section_articles"):
        links[r[0]].append(r[1])

    per_date: dict[str, list[str]] = collections.defaultdict(list)
    total_dates = 0
    for row in conn.execute(
        "SELECT * FROM report_sections WHERE category != 'additional_coverage' AND report_date >= ? ORDER BY report_date, id",
        (args.since,),
    ):
        section = dict(row)
        section["article_ids"] = links[row["id"]]
        total_dates += 1
        per_date[row["report_date"]].extend(f"section {row['id']}: {f}" for f in syn.audit_sections([section], articles))
    conn.close()

    flagged = {d: f for d, f in per_date.items() if f}
    for date in sorted(per_date):
        marker = f"{len(per_date[date])} flag(s)" if per_date[date] else "clean"
        print(f"{date}  {marker}")
        if args.verbose:
            for f in per_date[date]:
                print(f"    - {f}")
    print(f"\n{len(flagged)} of {len(per_date)} date(s) flagged, {sum(len(f) for f in flagged.values())} flag(s) in total.")
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
