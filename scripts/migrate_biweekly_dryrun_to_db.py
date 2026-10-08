"""One-off migration (2026-10-08): promotes the three already-built, already-
reviewed-and-approved biweekly dry-run periods (P1/P2/P3 - see PROJECT_LOG
4.80-4.84) from scripts/output/*.json into the new production tables
(biweekly_periods/biweekly_topics/biweekly_topic_sections). Reads the exact
already-approved content - does NOT call the API again, since that work was
already done and reviewed.

Run once: python -m scripts.migrate_biweekly_dryrun_to_db
Safe to re-run - skips (or with --force, overwrites) a period that already
exists in the DB, same convention as synthesize_biweekly.py itself.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from src.common.db import (
    biweekly_period_exists,
    delete_biweekly_period,
    get_connection,
    init_db,
    insert_biweekly_period,
    insert_biweekly_topic,
    link_biweekly_topic_section,
)

OUTPUT_DIR = Path(__file__).resolve().parent / "output"

PERIODS = [
    ("2026-08-20", "2026-09-02", "biweekly_stage2_dryrun_raw_2026-08-20_2026-09-02.json"),
    ("2026-09-03", "2026-09-16", "biweekly_stage2_dryrun_raw.json"),
    ("2026-09-17", "2026-09-30", "biweekly_stage2_dryrun_raw_2026-09-17_2026-09-30.json"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    conn = get_connection()
    init_db(conn)

    for start, end, fname in PERIODS:
        path = OUTPUT_DIR / fname
        if not path.exists():
            print(f"SKIP {start}..{end}: {path} not found.")
            continue
        if biweekly_period_exists(conn, end):
            if not args.force:
                print(f"SKIP {start}..{end}: already in DB (pass --force to overwrite).")
                continue
            delete_biweekly_period(conn, end)

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        overview = data["overview"]
        period_id = insert_biweekly_period(
            conn, start, end,
            overview["overview_he"], overview["overview_en"], overview["overview_de"],
            datetime.now(timezone.utc).isoformat(),
        )
        topics = sorted(data["topics"], key=lambda t: -t["n_sources"])
        for sort_order, t in enumerate(topics):
            r = t["result"]
            topic_id = insert_biweekly_topic(
                conn, period_id,
                r["topic_label_he"], r["topic_label_en"], r["topic_label_de"],
                r["comparison_text_he"], r["comparison_text_en"], r["comparison_text_de"],
                t["n_distinct_days"], t["n_sources"], sort_order,
            )
            # dict.fromkeys() de-dup, same generic-safety-net pattern already
            # used for duplicate article_ids in synthesize.py's stage-1
            # grouping - a section id can appear twice in one topic's own
            # list (harmless/expected, not the separate cross-topic
            # duplicate-assignment issue tracked in PROJECT_LOG 4.80).
            for section_id in dict.fromkeys(t["section_ids"]):
                link_biweekly_topic_section(conn, topic_id, section_id)
        print(f"WROTE {start}..{end}: period_id={period_id}, {len(topics)} topic(s).")

    conn.close()


if __name__ == "__main__":
    main()
