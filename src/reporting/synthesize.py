"""Reporting stage 1: synthesize cross-source topic sections for one report date.

Two-stage architecture: a single grouping pass (Sonnet, compact article fields only)
places every article into a real-world topic, then one comparison-writing call per
topic (Sonnet, full article fields, run concurrently with prompt caching on the
shared system prompt) writes the bilingual comparison. Replaces the original
single-mega-call design, which became unstable at 9+ sources / 250+ articles - see
PROJECT_LOG.md 4.23 for the failure history that motivated this.
Results are stored in reports / report_sections / report_section_articles.
Independent one-shot run - not a long-running daemon.
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
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

# Windows defaults stdout to the cp1252 console codepage even when redirected
# to a file, which raises UnicodeEncodeError on any print() containing a
# character outside it (e.g. Balkan/Slavic names) - fatal mid-run otherwise.
sys.stdout.reconfigure(encoding="utf-8")

MODEL = "claude-sonnet-5"

FALLBACK_PREFIX_HE = "כיסוי נוסף (לא שובץ להשוואה בין מקורות): "
FALLBACK_PREFIX_EN = "Additional coverage (not merged into a cross-source comparison): "

# Stage 1 (grouping) retry threshold - same value/spirit as the old single-call
# fallback threshold, now scoped narrowly to "did stage 1 place every article,"
# which is cheap to recheck and retry (one small call, not the whole day's work).
GROUPING_RATIO_THRESHOLD = 0.20

# Not rate-limit-driven (this tier allows far more - measured: 1000 req/min, 2M
# input tok/min, 400K output tok/min, vs. the ~25-30 calls a typical day needs) -
# a plain engineering choice for manageable error-handling/progress-reporting.
STAGE2_CONCURRENCY = 6

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

# --- Stage 1: topic grouping (one call/day, compact fields, no prose) -------

STAGE1_SYSTEM_PROMPT = """You are a synthesis editor for a geopolitical news-monitoring report, doing the first of two passes over today's articles. You will be given a compact list of individual articles already identified from today's editions of several newspapers - each with an id, source newspaper, headline, and an original per-article topic tag and stance summary (no full excerpt at this stage - that comes later).

Your task in this pass: group the articles by the actual real-world topic/story a reader would recognize as "the same conversation" - not by matching the literal per-article topic tag string, which was generated independently for each article and may use different wording for the same underlying subject. Use your own judgment of the substantive subject matter. Do NOT write any comparison prose in this pass - a later pass handles that, per topic, once grouping is settled.

The goal is an integrative picture of the day's major geopolitical issues - not maximally granular, one-article-per-topic splitting. If two or more articles, even from different sources, cover related aspects of the same broader issue, group them together even if their specific angle differs somewhat. When there is reasonable doubt about whether two articles belong together, prefer the broader, more richly-populated topic over a narrower split - a report of a few substantial, well-populated topics serves the reader's need for a coherent daily picture far better than many thin, single-article ones.

Rules:
- A topic can be covered by anywhere from one source to all of them.
- Every article id you were given must appear in exactly one topic's article_ids - do not omit any article, and do not place the same article in more than one topic.
- If two or more articles from the SAME newspaper describe the same specific event (for example, a front-page teaser and a fuller inside article about the same story), they still belong together in the same topic here - a later pass handles merging them into one voice.

For each topic, call record_topic_groups with one entry containing:
- topic_label_he / topic_label_en: a short section heading identifying the topic/story, in Hebrew and English respectively. Pay attention to correct Hebrew grammar, including gender agreement between numbers and nouns.
- category: the single best-fitting category for this topic, chosen from a fixed list (see the tool schema) - security_conflict, diplomacy_international, trade_economics, domestic_politics, migration_society, society_culture, technology_media, or energy_environment. Pick whichever category captures the topic's primary/dominant angle; every topic must get exactly one.
- article_ids: the ids of every input article belonging to this topic.

If you are given no articles, call record_topic_groups with an empty topics list."""

GROUP_TOOL = {
    "name": "record_topic_groups",
    "description": "Group today's articles into real-world topics, without writing comparison prose yet.",
    "input_schema": {
        "type": "object",
        "properties": {
            "topics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "topic_label_he": {"type": "string"},
                        "topic_label_en": {"type": "string"},
                        "category": {"type": "string", "enum": CATEGORIES},
                        "article_ids": {"type": "array", "items": {"type": "integer"}},
                    },
                    "required": ["topic_label_he", "topic_label_en", "category", "article_ids"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["topics"],
        "additionalProperties": False,
    },
    "strict": True,
}


def format_articles_compact(articles) -> str:
    blocks = []
    for a in articles:
        blocks.append(
            f"id={a['id']} | newspaper={a['newspaper']} | headline: {a['headline']}\n"
            f"  original topic tag: {a['region_topic']}\n"
            f"  stance: {a['stance_summary']}"
        )
    return "\n\n".join(blocks)


def group_articles_into_topics(client: anthropic.Anthropic, articles) -> tuple[list[dict], dict]:
    articles_text = format_articles_compact(articles)
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,  # well under the ~21,333 non-streaming cutoff for this model
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        system=STAGE1_SYSTEM_PROMPT,
        tools=[GROUP_TOOL],
        tool_choice={"type": "tool", "name": "record_topic_groups"},
        messages=[
            {
                "role": "user",
                "content": f"Today's articles ({len(articles)} total):\n\n{articles_text}",
            }
        ],
    )
    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
    }
    tool_use = next(b for b in response.content if b.type == "tool_use")
    topics = tool_use.input.get("topics")
    if not isinstance(topics, list):
        print(
            f"  warning: malformed stage-1 grouping response (stop_reason={response.stop_reason}, "
            f"no valid 'topics' list) - treating as 0 topics."
        )
        return [], usage
    return topics, usage


# --- Stage 2: per-topic comparison (one call/topic, full fields, cached) ----

STAGE2_SYSTEM_PROMPT = """You are a synthesis editor for a geopolitical news-monitoring report, writing the cross-source comparison for ONE already-identified topic (grouping already happened in an earlier pass). You will be given every article assigned to this topic - each with an id, source newspaper, headline, an original per-article topic tag, a stance summary, and a key excerpt.

Your task: write a comparative analysis (a few sentences to a short paragraph) of how the sources covering this topic frame it differently - their differing emphasis, stance, or angle - not a neutral summary of "what happened." If two or more articles from the SAME newspaper describe the same specific event (for example, a front-page teaser and a fuller inside article about the same story), treat them as ONE voice for that newspaper in your narrative - do not present that newspaper's position on the same event twice, even though you were given both ids. If only one source covers the topic, describe that source's stance/angle on its own.

Reference sources by name only - never by article id or page number. Article id numbers must NEVER appear inside comparison_text_he/en, in either language, even in parentheses. For example, write "The Daily Telegraph and Die Welt report..." - never "The Daily Telegraph (257, 265, 266) and Die Welt (284) report...". Write natural, fluent prose in each language conveying the same substantive content - not a mechanical translation of one into the other.

Newspaper names: whenever you refer to a source by name, you must use EXACTLY one of these forms, in their original Latin script - never transliterate, translate, abbreviate, or mix scripts, in either language: "The Guardian", "The Daily Telegraph", "Süddeutsche Zeitung", "Die Welt", "The New York Times International", "The Wall Street Journal", "Los Angeles Times", "USA Today", "The Economist", "Der Spiegel". This applies identically inside Hebrew text - a Latin-script proper name is never rendered in Hebrew letters. For example, a correct Hebrew sentence looks like: "The Daily Telegraph מדווח כי הממשלה הבריטית..." - never "הדיילי טלגרף", "טלגרף", or any other transliteration or mangled rendering of the name.

Hebrew grammar: comparison_text_he must be grammatically correct, standard Hebrew. Pay particular attention to gender agreement between numbers and the nouns they modify - for example "שתי זוויות" not "שני זוויות" (זווית is feminine), "שלוש כתבות" not "שלושה כתבות" (כתבה is feminine). Reread each Hebrew sentence you write for this kind of agreement error before finalizing it.

Call record_topic_comparison exactly once with comparison_text_he and comparison_text_en."""

COMPARE_TOOL = {
    "name": "record_topic_comparison",
    "description": "Record the cross-source comparison for this one topic.",
    "input_schema": {
        "type": "object",
        "properties": {
            "comparison_text_he": {"type": "string"},
            "comparison_text_en": {"type": "string"},
        },
        "required": ["comparison_text_he", "comparison_text_en"],
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


def write_topic_comparison(client: anthropic.Anthropic, topic: dict, topic_articles) -> tuple[dict, dict]:
    """Returns (usage, comparison). Raises on failure - caller handles retry/fallback."""
    articles_text = format_articles_for_prompt(topic_articles)
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": STAGE2_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[COMPARE_TOOL],
        tool_choice={"type": "tool", "name": "record_topic_comparison"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"Topic: {topic['topic_label_en']} / {topic['topic_label_he']}\n\n"
                    f"Articles ({len(topic_articles)} total):\n\n{articles_text}"
                ),
            }
        ],
    )
    tool_use = next(b for b in response.content if b.type == "tool_use")
    comparison = {
        "comparison_text_he": tool_use.input["comparison_text_he"],
        "comparison_text_en": tool_use.input["comparison_text_en"],
    }
    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
    }
    return usage, comparison


def write_topic_comparison_with_retry(client, topic, topic_articles):
    """One quick retry on failure; returns None (not an exception) if both attempts fail -
    the caller treats that topic's articles as needing individual fallback, exactly like
    any article stage 1 never assigned. A single topic's failure must never block the rest."""
    for attempt in range(2):
        try:
            return write_topic_comparison(client, topic, topic_articles)
        except Exception as exc:
            print(f"  topic '{topic['topic_label_en']}' attempt {attempt + 1} failed: {exc}")
    return None


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


def synthesize_day_two_stage(client: anthropic.Anthropic, articles) -> tuple[list[dict], list[dict]]:
    """Returns (sections, usage_log). sections omits any article stage 1 didn't assign,
    or whose topic failed stage 2 twice - run()'s existing fallback loop covers those,
    unchanged, exactly as it already does for any other gap."""
    valid_ids = {a["id"] for a in articles}
    articles_by_id = {a["id"]: a for a in articles}
    usage_log: list[dict] = []

    topics, stage1_usage = group_articles_into_topics(client, articles)
    usage_log.append({**stage1_usage, "stage": 1})
    unassigned = compute_missing_ids(topics, valid_ids)
    ratio = (len(unassigned) / len(valid_ids)) if valid_ids else 0

    if ratio > GROUPING_RATIO_THRESHOLD:
        print(
            f"  stage 1: {ratio:.0%} of articles unassigned exceeds {GROUPING_RATIO_THRESHOLD:.0%} "
            f"- retrying grouping once."
        )
        retry_topics, retry_usage = group_articles_into_topics(client, articles)
        usage_log.append({**retry_usage, "stage": 1})
        retry_unassigned = compute_missing_ids(retry_topics, valid_ids)
        retry_ratio = (len(retry_unassigned) / len(valid_ids)) if valid_ids else 0
        if retry_ratio < ratio:
            print(f"  stage 1 retry improved coverage ({ratio:.0%} -> {retry_ratio:.0%}) - using the retry result.")
            topics, ratio = retry_topics, retry_ratio
        else:
            print(f"  stage 1 retry did not improve coverage ({ratio:.0%} -> {retry_ratio:.0%}) - keeping the original grouping.")
        if ratio > GROUPING_RATIO_THRESHOLD:
            print(
                f"  *** QUALITY WARNING ***: stage-1 unassigned ratio {ratio:.0%} still exceeds "
                f"{GROUPING_RATIO_THRESHOLD:.0%} after retry - accepting as-is, needs human review."
            )
    print(f"  stage 1: {len(topics)} topic(s) grouped from {len(articles)} article(s).")

    if not topics:
        return [], usage_log

    def topic_articles_for(topic):
        return [articles_by_id[i] for i in topic["article_ids"] if i in articles_by_id]

    sections: list[dict] = []

    # Cache-warming: fire the first topic alone and let it fully complete before
    # fanning out the rest - concurrent identical-prefix requests can't read a
    # cache still being written by another in-flight request.
    first_topic = topics[0]
    result = write_topic_comparison_with_retry(client, first_topic, topic_articles_for(first_topic))
    if result is not None:
        usage, comparison = result
        usage_log.append({**usage, "stage": 2})
        sections.append({**first_topic, **comparison})
    else:
        print(f"  topic '{first_topic['topic_label_en']}' failed after retry - its articles will fall back individually.")

    remaining = topics[1:]
    if remaining:
        with ThreadPoolExecutor(max_workers=STAGE2_CONCURRENCY) as executor:
            future_to_topic = {
                executor.submit(write_topic_comparison_with_retry, client, topic, topic_articles_for(topic)): topic
                for topic in remaining
            }
            for future in as_completed(future_to_topic):
                topic = future_to_topic[future]
                result = future.result()
                if result is not None:
                    usage, comparison = result
                    usage_log.append({**usage, "stage": 2})
                    sections.append({**topic, **comparison})
                else:
                    print(f"  topic '{topic['topic_label_en']}' failed after retry - its articles will fall back individually.")

    return sections, usage_log


def run(report_date: str, force: bool = False, dry_run: bool = False) -> None:
    load_dotenv()

    conn = get_connection()
    init_db(conn)

    if not dry_run and report_exists(conn, report_date):
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
        f"Synthesizing {report_date}{' (DRY RUN - no DB writes)' if dry_run else ''}: "
        f"{len(articles)} article(s) from {len(sources)} source(s) ({', '.join(sources)})."
    )

    client = anthropic.Anthropic()
    valid_ids = {a["id"] for a in articles}

    sections, usage_log = synthesize_day_two_stage(client, articles)
    missing = compute_missing_ids(sections, valid_ids)
    coverage_ratio = 1 - ((len(missing) / len(valid_ids)) if valid_ids else 0)
    print(
        f"  coverage: {len(sections)} topic(s) with a real comparison, {len(missing)} article(s) "
        f"falling back individually ({coverage_ratio:.0%} of articles covered by a real comparison)."
    )

    for stage_num in (1, 2):
        stage_usage = [u for u in usage_log if u["stage"] == stage_num]
        if not stage_usage:
            continue
        total_input = sum(u["input_tokens"] for u in stage_usage)
        total_output = sum(u["output_tokens"] for u in stage_usage)
        total_cache_write = sum(u["cache_creation_input_tokens"] for u in stage_usage)
        total_cache_read = sum(u["cache_read_input_tokens"] for u in stage_usage)
        print(
            f"  stage {stage_num} usage across {len(stage_usage)} call(s): input={total_input}, output={total_output}, "
            f"cache_write={total_cache_write}, cache_read={total_cache_read}"
        )

    if dry_run:
        articles_per_topic = (len(valid_ids) - len(missing)) / len(sections) if sections else 0
        print(f"  articles/topic ratio: {articles_per_topic:.2f} ({len(valid_ids) - len(missing)} articles / {len(sections)} topics)")
        print("\n  --- sample sections (first 4) ---")
        for section in sections[:4]:
            print(f"\n  [{section['category']}] {section['topic_label_en']} / {section['topic_label_he']}")
            print(f"    {len(section['article_ids'])} article(s): {section['article_ids']}")
            print(f"    EN: {section['comparison_text_en']}")
            print(f"    HE: {section['comparison_text_he']}")
        print(
            f"\nDry run complete for {report_date}: {len(sections)} section(s) would be written, "
            f"{len(missing)} article(s) would fall back individually. No DB writes performed."
        )
        conn.close()
        return

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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run both stages and print results/usage stats without writing to the DB at all.",
    )
    args = parser.parse_args()
    run(report_date=args.date, force=args.force, dry_run=args.dry_run)
