"""Reporting stage 1: synthesize cross-source topic sections for one report date.

Reads every article extracted (Analysis stage) from downloaded_files published on
a given date across all newspapers, and makes a single Claude Sonnet call that
groups them by real-world topic (not by the raw per-article region_topic string),
merges same-newspaper duplicate-event articles into one voice per source, and
writes a bilingual (Hebrew/English) cross-source comparison per topic group.
Results are stored in reports / report_sections / report_section_articles.
Independent one-shot run - not a long-running daemon. Render (stage 2) is a
separate, not-yet-implemented script that will read these tables.
"""

import argparse
import json
from datetime import datetime, timezone

import anthropic
from dotenv import load_dotenv

from src.common.db import (
    delete_report,
    get_articles_for_date,
    get_connection,
    get_sources_for_date,
    init_db,
    insert_report,
    insert_report_section,
    link_section_article,
    report_exists,
)

MODEL = "claude-sonnet-5"

FALLBACK_PREFIX_HE = "כיסוי נוסף (לא שובץ להשוואה בין מקורות): "
FALLBACK_PREFIX_EN = "Additional coverage (not merged into a cross-source comparison): "

FALLBACK_RATIO_THRESHOLD = 0.20

CATEGORIES = [
    "security_conflict",
    "diplomacy_international",
    "trade_economics",
    "domestic_politics",
    "migration_society",
    "society_culture",
    "technology_media",
    "energy_environment",
]

FALLBACK_CATEGORY = "additional_coverage"

SYSTEM_PROMPT = """You are a synthesis editor for a geopolitical news-monitoring report. You will be given a list of individual articles already identified from today's editions of several newspapers - each with an id, source newspaper, headline, an original per-article topic tag, a stance summary, and a key excerpt.

Your task: produce the day's report as a set of topic-grouped sections comparing how the different sources cover each real-world story or theme, in both Hebrew and English.

For grouping:
- Group articles by the actual real-world topic/story a reader would recognize as "the same conversation" - not by matching the literal per-article topic tag string, which was generated independently for each article and may use different wording for the same underlying subject. Use your own judgment of the substantive subject matter.
- If two or more articles from the SAME newspaper describe the same specific event (for example, a short front-page teaser and a fuller inside article about the same story - this happens because of the source's front-page/inside-page structure), treat them as ONE voice for that newspaper in your comparison narrative - do not present that newspaper's position on the same event twice. Still include all of their ids in article_ids for that section, even though you've merged them narratively.
- A topic can be covered by anywhere from one source to all of them.
- Every article id you were given must appear in exactly one section's article_ids - do not omit any article, and do not place the same article in more than one section.

For each section, call record_report_sections with one entry containing:
- topic_label_he / topic_label_en: a short section heading identifying the topic/story, in Hebrew and English respectively.
- comparison_text_he / comparison_text_en: a comparative analysis (a few sentences to a short paragraph) of how the sources covering this topic frame it differently - their differing emphasis, stance, or angle - not a neutral summary of "what happened." Reference sources by name only - never by article id or page number. Article id numbers must NEVER appear inside comparison_text_he/en, in either language, even in parentheses - they belong exclusively in the structured article_ids field. For example, write "The Daily Telegraph and Die Welt report..." - never "The Daily Telegraph (257, 265, 266) and Die Welt (284) report...". If only one source covers the topic, describe that source's stance/angle on its own. Write natural, fluent prose in each language conveying the same substantive content - not a mechanical translation of one into the other.
- article_ids: the ids of every input article this section is based on, including every member of any merged same-newspaper duplicate.
- category: the single best-fitting category for this section, chosen from a fixed list (see the tool schema) - security_conflict, diplomacy_international, trade_economics, domestic_politics, migration_society, society_culture, technology_media, or energy_environment. Pick whichever category captures the section's primary/dominant angle; every section must get exactly one.

Newspaper names: whenever you refer to a source by name inside comparison_text_he or comparison_text_en, you must use EXACTLY one of these four forms, in their original Latin script - never transliterate, translate, abbreviate, or mix scripts, in either language: "The Guardian", "The Daily Telegraph", "Süddeutsche Zeitung", "Die Welt". This applies identically inside Hebrew text - a Latin-script proper name is never rendered in Hebrew letters. For example, a correct Hebrew sentence looks like: "The Daily Telegraph מדווח כי הממשלה הבריטית..." - never "הדיילי טלגרף", "טלגרף", "זюддойче צייטונג", or any other transliteration or mangled rendering of the name.

Hebrew grammar: comparison_text_he must be grammatically correct, standard Hebrew. Pay particular attention to gender agreement between numbers and the nouns they modify - for example "שתי זוויות" not "שני זוויות" (זווית is feminine), "שלוש כתבות" not "שלושה כתבות" (כתבה is feminine). Reread each Hebrew sentence you write for this kind of agreement error before finalizing it.

If you are given no articles, call record_report_sections with an empty sections list."""

SYNTHESIZE_TOOL = {
    "name": "record_report_sections",
    "description": "Record the day's report as topic-grouped sections comparing how different newspapers cover each topic.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "topic_label_he": {"type": "string"},
                        "topic_label_en": {"type": "string"},
                        "comparison_text_he": {"type": "string"},
                        "comparison_text_en": {"type": "string"},
                        "article_ids": {"type": "array", "items": {"type": "integer"}},
                        "category": {"type": "string", "enum": CATEGORIES},
                    },
                    "required": [
                        "topic_label_he",
                        "topic_label_en",
                        "comparison_text_he",
                        "comparison_text_en",
                        "article_ids",
                        "category",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["sections"],
        "additionalProperties": False,
    },
    "strict": True,
}


def format_articles_for_prompt(articles) -> str:
    blocks = []
    for a in articles:
        blocks.append(
            f"id={a['id']} | newspaper={a['newspaper']} | headline: {a['headline']}\n"
            f"  original topic tag: {a['region_topic']}\n"
            f"  stance: {a['stance_summary']}\n"
            f'  excerpt: "{a["key_excerpt"]}"'
        )
    return "\n\n".join(blocks)


def build_fallback_section(article) -> dict:
    return {
        "topic_label_he": article["region_topic"],
        "topic_label_en": article["region_topic"],
        "comparison_text_he": (
            f'{FALLBACK_PREFIX_HE}{article["stance_summary"]} ציטוט מרכזי: "{article["key_excerpt"]}"'
        ),
        "comparison_text_en": (
            f'{FALLBACK_PREFIX_EN}{article["stance_summary"]} Key excerpt: "{article["key_excerpt"]}"'
        ),
        "category": FALLBACK_CATEGORY,
    }


def compute_missing_ids(sections, valid_ids: set) -> set:
    seen = set()
    for section in sections:
        seen.update(a for a in section["article_ids"] if a in valid_ids)
    return valid_ids - seen


def synthesize_day(client: anthropic.Anthropic, articles) -> list[dict]:
    articles_text = format_articles_for_prompt(articles)
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        system=SYSTEM_PROMPT,
        tools=[SYNTHESIZE_TOOL],
        tool_choice={"type": "tool", "name": "record_report_sections"},
        messages=[
            {
                "role": "user",
                "content": f"Today's articles ({len(articles)} total):\n\n{articles_text}",
            }
        ],
    )
    tool_use = next(b for b in response.content if b.type == "tool_use")
    return tool_use.input["sections"]


def run(report_date: str, force: bool = False) -> None:
    load_dotenv()

    conn = get_connection()
    init_db(conn)

    if report_exists(conn, report_date):
        if not force:
            print(f"Report for {report_date} already exists - skipping (use --force to rebuild).")
            conn.close()
            return
        print(f"Report for {report_date} already exists - deleting and rebuilding (--force).")
        delete_report(conn, report_date)

    sources = get_sources_for_date(conn, report_date)
    if not sources:
        print(f"No downloaded files found for {report_date} - nothing to synthesize.")
        conn.close()
        return
    if len(sources) < 4:
        print(f"Warning: only {len(sources)} source(s) available for {report_date}: {', '.join(sources)}")

    articles = get_articles_for_date(conn, report_date)
    if not articles:
        print(f"No articles found for {report_date} - nothing to synthesize.")
        conn.close()
        return

    print(
        f"Synthesizing {report_date}: {len(articles)} article(s) from "
        f"{len(sources)} source(s) ({', '.join(sources)})."
    )

    client = anthropic.Anthropic()
    valid_ids = {a["id"] for a in articles}

    sections = synthesize_day(client, articles)
    missing = compute_missing_ids(sections, valid_ids)
    fallback_ratio = len(missing) / len(valid_ids)

    if fallback_ratio > FALLBACK_RATIO_THRESHOLD:
        print(
            f"  fallback ratio {fallback_ratio:.0%} exceeds {FALLBACK_RATIO_THRESHOLD:.0%} "
            f"- retrying once with identical input."
        )
        retry_sections = synthesize_day(client, articles)
        retry_missing = compute_missing_ids(retry_sections, valid_ids)
        retry_ratio = len(retry_missing) / len(valid_ids)
        if retry_ratio < fallback_ratio:
            print(f"  retry improved the fallback ratio ({fallback_ratio:.0%} -> {retry_ratio:.0%}) - using the retry result.")
            sections, fallback_ratio = retry_sections, retry_ratio
        else:
            print(f"  retry did not improve the fallback ratio ({fallback_ratio:.0%} -> {retry_ratio:.0%}) - keeping the original result.")
        if fallback_ratio > FALLBACK_RATIO_THRESHOLD:
            print(
                f"  *** QUALITY WARNING ***: fallback ratio {fallback_ratio:.0%} still exceeds "
                f"{FALLBACK_RATIO_THRESHOLD:.0%} after retry - accepting as-is, needs human review."
            )

    now = datetime.now(timezone.utc).isoformat()
    insert_report(conn, report_date, json.dumps(sources, ensure_ascii=False), now)

    seen_ids = set()
    for section in sections:
        section_id = insert_report_section(
            conn,
            report_date,
            section["topic_label_he"],
            section["topic_label_en"],
            section["comparison_text_he"],
            section["comparison_text_en"],
            section["category"],
            now,
        )
        for article_id in section["article_ids"]:
            if article_id not in valid_ids:
                print(
                    f"  warning: section '{section['topic_label_en']}' references unknown "
                    f"article_id={article_id} - skipping link."
                )
                continue
            link_section_article(conn, section_id, article_id)
            seen_ids.add(article_id)
        print(f"  section: {section['topic_label_en']} ({len(section['article_ids'])} article(s))")

    missing = valid_ids - seen_ids
    if missing:
        articles_by_id = {a["id"]: a for a in articles}
        for article_id in sorted(missing):
            fallback = build_fallback_section(articles_by_id[article_id])
            section_id = insert_report_section(
                conn,
                report_date,
                fallback["topic_label_he"],
                fallback["topic_label_en"],
                fallback["comparison_text_he"],
                fallback["comparison_text_en"],
                fallback["category"],
                now,
            )
            link_section_article(conn, section_id, article_id)
            print(f"  fallback section created for article_id={article_id}: {fallback['topic_label_en']}")

    conn.close()
    print(
        f"\nSynthesis complete: {len(sections)} model section(s) + {len(missing)} fallback section(s) "
        f"= {len(sections) + len(missing)} total for {report_date}."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Reporting stage 1: synthesize cross-source topic sections for one report date."
    )
    parser.add_argument("--date", required=True, help="Report date to synthesize, format YYYY-MM-DD.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete and rebuild an already-synthesized report for this date.",
    )
    args = parser.parse_args()
    run(report_date=args.date, force=args.force)
