"""Backfill country/conflict-zone tags for articles analyzed before geo-tagging existed.

Reusable, rerunnable utility - not a one-off throwaway script. Reads articles that
already have headline/region_topic/stance_summary (from analyze.py) but no rows yet
in article_countries/article_conflict_zones, and classifies them in batches (not one
API call per article) with a cheap Haiku call using the same closed taxonomy that
analyze.py now applies going forward. No extended thinking - this is a simple
closed-set classification task, same cost profile as screen.py's binary check.

Idempotent by construction: an article only shows up in get_articles_without_geo_tags
until it has at least one row in either new table, so a partial or failed run is safe
to simply re-run later - no separate fallback/retry machinery needed (unlike
synthesize.py, where sections are interdependent within one call).
"""

import argparse

import anthropic
from dotenv import load_dotenv

from src.common.db import (
    get_articles_without_geo_tags,
    get_connection,
    init_db,
    insert_article_conflict_zones,
    insert_article_countries,
)
from src.common.geo_taxonomy import CONFLICT_ZONE_LABELS, country_codes, country_list_prompt_text

MODEL = "claude-haiku-4-5-20251001"
BATCH_SIZE = 25

SYSTEM_PROMPT = """You are tagging previously-analyzed geopolitical articles with structured country and conflict-zone labels, for a batch of articles at once.

For each article below (given by id, headline, topic tag, and stance summary), call record_geo_tags with one entry per article containing:
- article_id: the id exactly as given.
- country_codes: zero or more ISO country codes from this closed list that the article substantively concerns (not just a passing mention) - {country_list}. A piece about US-Iran policy should include both "US" and "IR". If no specific country from this list applies, leave empty.
- conflict_zones: zero or more of israel_palestine_conflict, iran_west_conflict, russia_ukraine_conflict - ONLY if the article substantively concerns that specific conflict. Most articles concern none of these; do not force a match.

You must return exactly one entry per article id given, in any order.""".format(country_list=country_list_prompt_text())

BACKFILL_GEO_TOOL = {
    "name": "record_geo_tags",
    "description": "Record country and conflict-zone tags for each article in this batch.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tags": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "article_id": {"type": "integer"},
                        "country_codes": {"type": "array", "items": {"type": "string", "enum": country_codes()}},
                        "conflict_zones": {
                            "type": "array",
                            "items": {"type": "string", "enum": list(CONFLICT_ZONE_LABELS.keys())},
                        },
                    },
                    "required": ["article_id", "country_codes", "conflict_zones"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["tags"],
        "additionalProperties": False,
    },
    "strict": True,
}


def format_batch_for_prompt(articles) -> str:
    blocks = []
    for a in articles:
        blocks.append(
            f"id={a['id']}\n"
            f"  headline: {a['headline']}\n"
            f"  topic tag: {a['region_topic']}\n"
            f"  stance: {a['stance_summary']}"
        )
    return "\n\n".join(blocks)


def tag_batch(client: anthropic.Anthropic, articles) -> list[dict]:
    batch_text = format_batch_for_prompt(articles)
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[BACKFILL_GEO_TOOL],
        tool_choice={"type": "tool", "name": "record_geo_tags"},
        messages=[
            {
                "role": "user",
                "content": f"Articles to tag ({len(articles)} total):\n\n{batch_text}",
            }
        ],
    )
    tool_use = next(b for b in response.content if b.type == "tool_use")
    return tool_use.input["tags"]


def run(report_date: str | None = None) -> None:
    load_dotenv()

    conn = get_connection()
    init_db(conn)

    articles = get_articles_without_geo_tags(conn, report_date=report_date)
    if not articles:
        print("No untagged articles found - nothing to do.")
        conn.close()
        return

    print(f"Tagging {len(articles)} article(s) without geo tags, in batches of {BATCH_SIZE}.")

    client = anthropic.Anthropic()
    batches_ok = 0
    batches_failed = 0
    articles_tagged = 0

    for start in range(0, len(articles), BATCH_SIZE):
        batch = articles[start : start + BATCH_SIZE]
        batch_ids = {a["id"] for a in batch}

        try:
            tags = tag_batch(client, batch)
        except Exception as exc:
            batches_failed += 1
            print(f"  batch starting at article_id={batch[0]['id']} failed: {exc}")
            continue

        seen_ids = set()
        for tag in tags:
            article_id = tag["article_id"]
            if article_id not in batch_ids:
                print(f"  warning: response references unknown article_id={article_id} - skipping.")
                continue
            insert_article_countries(conn, article_id, tag["country_codes"])
            insert_article_conflict_zones(conn, article_id, tag["conflict_zones"])
            seen_ids.add(article_id)
            articles_tagged += 1

        missing = batch_ids - seen_ids
        if missing:
            print(f"  warning: {len(missing)} article(s) not tagged in this batch, will retry next run: {sorted(missing)}")

        batches_ok += 1
        print(f"  batch {start}-{start + len(batch) - 1}: {len(seen_ids)}/{len(batch)} tagged")

    conn.close()
    print(
        f"\nGeo-tag backfill complete: {batches_ok} batch(es) succeeded, {batches_failed} batch(es) failed, "
        f"{articles_tagged} article(s) tagged in total."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill country/conflict-zone tags for articles analyzed before geo-tagging existed."
    )
    parser.add_argument(
        "--date",
        dest="report_date",
        help="Limit to articles published on this date (YYYY-MM-DD), for testing on a sample.",
    )
    args = parser.parse_args()
    run(report_date=args.report_date)
