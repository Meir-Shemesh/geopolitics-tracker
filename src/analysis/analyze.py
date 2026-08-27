"""Stage 2 of Analysis: deep article extraction with Claude Sonnet.

Reads only pages that screen.py (Stage 1) already flagged is_relevant=1 and
that have not yet been analyzed, identifies individual opinion/commentary
articles on each page (accounting for the magazine/grid layout's non-
contiguous text - see HANDOFF.md "בעיות ידועות"), and records one row per
article in the articles table. Independent of screen.py - only reads its
output. One-shot run - not a long-running daemon.
"""

import argparse
from datetime import datetime, timezone

import anthropic
from dotenv import load_dotenv

from src.common.db import (
    get_connection,
    get_pages_pending_analysis,
    init_db,
    insert_article,
    insert_article_conflict_zones,
    insert_article_countries,
    set_analysis_status,
)
from src.common.geo_taxonomy import CONFLICT_ZONE_LABELS, country_codes, country_list_prompt_text

MODEL = "claude-sonnet-5"

NEWSPAPER_LANGUAGES = {
    "Guardian": "en",
    "Daily Telegraph": "en",
    "Süddeutsche Zeitung": "de",
    "Die Welt": "de",
}

SYSTEM_PROMPT = """You are a geopolitical content analyst for a news-monitoring pipeline. You will be shown the raw text extracted from one newspaper page that has already been flagged as likely containing geopolitical opinion/commentary content.

Important: the source PDF uses a magazine/grid layout, not simple text columns. The extracted text may interleave paragraphs from multiple unrelated articles that happen to sit in adjacent boxes on the same physical page - sentences from different stories can appear next to each other out of true reading order. Use topic, tone, and narrative continuity (not just text order) to determine where one article ends and another begins.

For every distinct piece of geopolitical opinion, analysis, or commentary you can identify on this page (there may be zero, one, or several), call record_articles with one entry per article containing:
- headline: the article's headline/title as it appears, or a short descriptive title you construct if none is clearly printed.
- author: the byline name if present, otherwise an empty string. Only fill this in if you are confident the name belongs to THIS article - if there is any doubt that a nearby name is actually leaked text from an adjacent box (a real risk given the grid layout), leave it as an empty string rather than guess. An empty author is far better than a wrong one.
- region_topic: the primary geopolitical region or topic the piece concerns (e.g. "Russia-Ukraine war", "US-China trade relations", "Middle East / Gaza").
- stance_summary: 1-2 sentences summarizing the author's central argument or position - not a neutral topic description, the actual stance taken.
- key_excerpt: one short verbatim quotation (under 40 words) from the text that best represents the piece's core claim.
- country_codes: zero or more ISO country codes from this closed list that the article substantively concerns (not just a passing mention) - {country_list}. A piece about US-Iran policy should include both "US" and "IR". If no specific country from this list applies, leave empty.
- conflict_zones: zero or more of israel_palestine_conflict, iran_west_conflict, russia_ukraine_conflict - ONLY if the article substantively concerns that specific conflict. Most articles concern none of these; do not force a match.

A piece qualifies as "geopolitical" only if it concerns international relations, foreign policy, cross-border conflicts, diplomacy, sanctions, geopolitical economics, or a similar international/cross-border dimension. Exclude opinion pieces about purely domestic policy that have no such dimension, even if they are legitimate, substantive political commentary - for example, exclude an op-ed arguing about a domestic pension reform, or one about retail workers' wages and unionization, if neither has an international angle. Also exclude news-brief items, factual reporting without an opinion angle, and content unrelated to geopolitics (culture, sport, lifestyle, etc.).

If nothing on the page qualifies, call record_articles with an empty articles list.""".format(country_list=country_list_prompt_text())

ANALYZE_TOOL = {
    "name": "record_articles",
    "description": "Record every distinct opinion/commentary article identified on this page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "articles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "headline": {"type": "string"},
                        "author": {"type": "string"},
                        "region_topic": {"type": "string"},
                        "stance_summary": {"type": "string"},
                        "key_excerpt": {"type": "string"},
                        "country_codes": {"type": "array", "items": {"type": "string", "enum": country_codes()}},
                        "conflict_zones": {
                            "type": "array",
                            "items": {"type": "string", "enum": list(CONFLICT_ZONE_LABELS.keys())},
                        },
                    },
                    "required": [
                        "headline",
                        "author",
                        "region_topic",
                        "stance_summary",
                        "key_excerpt",
                        "country_codes",
                        "conflict_zones",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["articles"],
        "additionalProperties": False,
    },
    "strict": True,
}


def analyze_page(client: anthropic.Anthropic, newspaper: str, raw_text: str) -> list[dict]:
    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        system=SYSTEM_PROMPT,
        tools=[ANALYZE_TOOL],
        tool_choice={"type": "tool", "name": "record_articles"},
        messages=[{"role": "user", "content": f"Newspaper: {newspaper}\nPage text:\n\n{raw_text}"}],
    )
    tool_use = next(b for b in response.content if b.type == "tool_use")
    return tool_use.input["articles"]


def run(file_id: int | None = None) -> None:
    load_dotenv()

    conn = get_connection()
    init_db(conn)

    pages = get_pages_pending_analysis(conn, file_id=file_id)
    client = anthropic.Anthropic()

    pages_analyzed = 0
    pages_failed = 0
    total_articles = 0

    for page in pages:
        newspaper = page["newspaper"]
        language = NEWSPAPER_LANGUAGES.get(newspaper, "")

        try:
            articles = analyze_page(client, newspaper, page["raw_text"])
        except Exception as exc:
            pages_failed += 1
            print(f"  failed: file_id={page['file_id']} page={page['page_number']} ({exc})")
            continue

        now = datetime.now(timezone.utc).isoformat()
        for article in articles:
            article_id = insert_article(
                conn,
                page["file_id"],
                page["page_number"],
                newspaper,
                language,
                article["headline"],
                article["author"],
                article["region_topic"],
                article["stance_summary"],
                article["key_excerpt"],
                now,
            )
            insert_article_countries(conn, article_id, article["country_codes"])
            insert_article_conflict_zones(conn, article_id, article["conflict_zones"])

        set_analysis_status(conn, page["file_id"], page["page_number"], "completed")
        pages_analyzed += 1
        total_articles += len(articles)
        print(f"  page {page['page_number']} (file {page['file_id']}): {len(articles)} article(s)")

    conn.close()

    print(
        f"\nAnalysis: {pages_analyzed} page(s) analyzed, {pages_failed} page(s) failed, "
        f"{total_articles} article(s) identified in total"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage 2: deep article extraction with Claude Sonnet.")
    parser.add_argument(
        "--file-id",
        type=int,
        help="Limit to pages belonging to this downloaded_files.id (for testing on a sample).",
    )
    args = parser.parse_args()
    run(file_id=args.file_id)
