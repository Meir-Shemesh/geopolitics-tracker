"""One-off (2026-09-24, PROJECT_LOG action item 45): fixes two report_sections rows
whose comparison_text_he came back broken from Stage 2 of synthesize.py - id=2311
(2026-09-20, "only") and id=2494 (2026-09-22, "0"). Both were discovered during
unrelated visual QA of the topic.html export/print feature, not by any automated
check (the guard added alongside this script, _looks_suspicious() in synthesize.py,
did not exist yet when these were generated).

Re-runs ONLY stage 2 (write_topic_comparison_with_retry, now guarded) for these two
sections specifically - not stage 1, not a full day's synthesize run - using the
exact same topic label context and linked articles already in the DB. Only
comparison_text_he is written back; comparison_text_en/de and topic_label_de are
read from the fresh call for logging/comparison only and are explicitly NOT written
to the DB, since neither was reported broken for these two rows (comparison_text_en
for id=2311 is a separate, already-flagged, NOT-in-scope-here issue - see
PROJECT_LOG 4.49/action item 45 - left untouched on purpose).

Not safe to run again blindly: it will simply regenerate a fresh Hebrew comparison
for these two sections every time, which may differ text from run to run (Claude is
not deterministic) - intentionally one-off, matching id=200/id=205's precedent of
one-off DB fixes in this file's sibling scripts.
"""
import sys

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

import anthropic
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")

from src.common.db import get_connection, init_db
from src.reporting.synthesize import _looks_suspicious, write_topic_comparison_with_retry

SECTION_IDS = (2311, 2494)


def get_section_row(conn, section_id):
    return conn.execute(
        "SELECT id, report_date, topic_label_he, topic_label_en, comparison_text_he, "
        "comparison_text_en, comparison_text_de FROM report_sections WHERE id = ?",
        (section_id,),
    ).fetchone()


def get_linked_articles(conn, section_id):
    return conn.execute(
        """
        SELECT a.id, a.newspaper, a.headline, a.region_topic, a.stance_summary, a.key_excerpt
        FROM articles a
        JOIN report_section_articles rsa ON rsa.article_id = a.id
        WHERE rsa.section_id = ?
        ORDER BY a.id
        """,
        (section_id,),
    ).fetchall()


def main():
    conn = get_connection()
    init_db(conn)
    client = anthropic.Anthropic()

    total_cost = 0.0
    # Sonnet 5 pricing - matches synthesize.py's MODEL constant, the only model this
    # script uses (no --stage1-model style override here - this is stage 2, which
    # CLAUDE.md's fixed rule keeps on the production model regardless).
    PRICE_IN, PRICE_OUT = 2.00, 10.00

    for section_id in SECTION_IDS:
        row = get_section_row(conn, section_id)
        if row is None:
            print(f"section {section_id}: NOT FOUND - skipping")
            continue

        print(f"\n=== section {section_id} (report {row['report_date']}) ===")
        print(f"  topic: {row['topic_label_en']} / {row['topic_label_he']}")
        print(f"  BEFORE - he: {row['comparison_text_he']!r}")
        print(f"  BEFORE - en (untouched either way): {row['comparison_text_en'][:80]!r}...")

        articles = get_linked_articles(conn, section_id)
        if not articles:
            print(f"  no linked articles found - skipping (cannot regenerate without source material)")
            continue
        print(f"  {len(articles)} linked article(s): {[a['id'] for a in articles]}")

        topic = {"topic_label_he": row["topic_label_he"], "topic_label_en": row["topic_label_en"]}
        result = write_topic_comparison_with_retry(client, topic, articles)
        if result is None:
            print(f"  FAILED - both attempts (including the guard's automatic retry) were rejected. Not written.")
            continue
        usage, comparison = result

        cost = (usage["input_tokens"] * PRICE_IN + usage["output_tokens"] * PRICE_OUT) / 1_000_000
        total_cost += cost
        print(f"  usage: in={usage['input_tokens']} out={usage['output_tokens']} -> ${cost:.4f}")

        new_he = comparison["comparison_text_he"]
        if _looks_suspicious(new_he):
            print(f"  ABORTING WRITE - fresh comparison_text_he still looks suspicious: {new_he!r}")
            continue

        print(f"  AFTER  - he: {new_he[:120]!r}...")
        print(f"  (fresh en/de from this call, NOT written - shown for reference only)")
        print(f"    en: {comparison['comparison_text_en'][:80]!r}...")
        print(f"    de: {comparison['comparison_text_de'][:80]!r}...")

        conn.execute(
            "UPDATE report_sections SET comparison_text_he = ? WHERE id = ?",
            (new_he, section_id),
        )
        conn.commit()
        print(f"  WROTE comparison_text_he for section {section_id}.")

    conn.close()
    print(f"\n=== DONE - total cost ${total_cost:.4f} ===")


if __name__ == "__main__":
    main()
