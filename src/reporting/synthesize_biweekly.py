"""Reporting stage for the biweekly narrative-trends report - promoted from the
scripts/biweekly_stage{1,2}_dryrun.py dry-run tooling (PROJECT_LOG 4.80-4.84)
to a real pipeline stage, writing to tracker.db instead of local JSON/MD
files. See CLAUDE.md "דוח דו-שבועי" for the full specification this
implements: Thu-Wed 14-day cadence (src/common/biweekly.py), >=5-distinct-day
inclusion threshold, the conclusion-first/2-3-examples Stage 2 structure with
per-tier word ceilings, and the three Stage 2 guards (placeholder detection,
word-ceiling enforcement, newspaper-name whitelist).

Two-stage architecture, same shape as the dry-run tooling it replaces:
  Stage 1 (map-reduce): splits the period's daily report_sections into
    token-budgeted windows, groups each window's sections into real-world
    story threads (map), then merges all windows' groups into one final
    cross-period topic list (reduce). Both steps share one retry-once policy
    (BIWEEKLY_GROUPING_RATIO_THRESHOLD, deliberately separate from
    synthesize.py's own GROUPING_RATIO_THRESHOLD - see PROJECT_LOG 4.80/4.82
    for why 20% doesn't fit this step).
  Stage 2: one narrative-writing call per topic that cleared the inclusion
    threshold (feedback-informed retry on any guard failure), plus one short
    overview call.

Called either with an explicit --start/--end (manual re-run / backfill) or
with neither, in which case it only acts if today is the closing date of a
period (src.common.biweekly.period_closing_on) - the mode daily_autorun.py's
conditional biweekly step uses.
"""
import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

import anthropic
from dotenv import load_dotenv

from src.common.biweekly import period_closing_on
from src.common.db import (
    biweekly_period_exists,
    delete_biweekly_period,
    get_connection,
    init_db,
    insert_biweekly_period,
    insert_biweekly_topic,
    link_biweekly_topic_section,
)
from src.reporting.render import NEWSPAPER_DISPLAY_NAMES
from src.reporting.synthesize import _GERMAN_STYLE_ANCHOR, _looks_suspicious, compute_stage1_problem_ratio

load_dotenv()

MODEL = "claude-sonnet-5"
CONCURRENCY = 6

# Deliberately separate from synthesize.py's GROUPING_RATIO_THRESHOLD (20%) -
# that one is calibrated for daily Stage 1's near-total-failure days; this one
# is calibrated from the biweekly map-reduce's own measured ratios (clean
# windows ~4-11%, the two known duplicate-contamination cases ~9.65-11.5%).
# See PROJECT_LOG 4.80/4.82.
BIWEEKLY_GROUPING_RATIO_THRESHOLD = 0.08

TARGET_TOKENS_PER_MAP_WINDOW = 45000
GIST_CHARS = 280

MIN_DISTINCT_DAYS = 5

WORD_CEILINGS = {"deep": 140, "developed": 100, "concise": 70}

DEPTH_INSTRUCTIONS = {
    "deep": (
        "This topic spans a large majority of the two-week period (a 'deep' topic) - "
        "write up to 2-3 selected examples (not a day-by-day account) illustrating your "
        f"conclusion. Hard limit: {WORD_CEILINGS['deep']} words for comparison_text_he/en/de "
        "each - this is measured after you write and you will be asked to cut it down if "
        "you exceed it, so budget your words accordingly rather than writing long and "
        "expecting it to be trimmed later."
    ),
    "developed": (
        "This topic spans a meaningful stretch of the two-week period (a 'developed' "
        "topic, not the most dominant but a real recurring story) - use up to 2 selected "
        f"examples. Hard limit: {WORD_CEILINGS['developed']} words for comparison_text_he/en/de "
        "each, measured after you write."
    ),
    "concise": (
        "This topic is close to the inclusion threshold (a 'concise' topic) - use at "
        f"most 1-2 selected examples. Hard limit: {WORD_CEILINGS['concise']} words for "
        "comparison_text_he/en/de each, measured after you write."
    ),
}


def depth_tier(n_days: int) -> str:
    if n_days >= 8:
        return "deep"
    if n_days >= 5:
        return "developed"
    return "concise"


def word_count(text: str) -> int:
    return len((text or "").split())


def over_ceiling_langs(result: dict, tier: str) -> dict[str, int]:
    ceiling = WORD_CEILINGS[tier]
    over = {}
    for lang in ("he", "en", "de"):
        n = word_count(result[f"comparison_text_{lang}"])
        if n > ceiling:
            over[lang] = n
    return over


# Exact Latin-script forms the rule requires - taken directly from render.py's
# NEWSPAPER_DISPLAY_NAMES, never re-typed, so this can never drift from the
# canonical list.
APPROVED_NEWSPAPER_NAMES_LATIN = list(NEWSPAPER_DISPLAY_NAMES.values())

# Distinctive Hebrew-letter transliteration fragments that would only
# plausibly appear if a newspaper name was rendered in Hebrew letters instead
# of its required Latin-script form - see PROJECT_LOG 4.82/4.83 for the full
# investigation (garbled mixed-script forms, clean-Hebrew-letter forms, and
# the discovery that this is also a pre-existing daily-production issue,
# fixed retroactively for the daily archive separately - action item 72).
TRANSLITERATION_TELLS = {
    "צייטונג": "Süddeutsche Zeitung",
    "שפיגל": "Der Spiegel",
    "טלגרף": "The Daily Telegraph",
    "גארדיין": "The Guardian",
    "גרדיאן": "The Guardian",
    "גארדיאן": "The Guardian",
    "אקונומיסט": "The Economist",
    "ג'ורנל": "The Wall Street Journal",
    "ג'רנל": "The Wall Street Journal",
    "וול סטריט": "The Wall Street Journal",
    "וושינגטון פוסט": "The Washington Post",
    "לוס אנג'לס": "Los Angeles Times",
    "טיימס": "Los Angeles Times / The New York Times International",
    "טודיי": "USA Today",
    "די וולט": "Die Welt",
    "די ולט": "Die Welt",
}


def hebrew_newspaper_violations(text: str) -> dict[str, str]:
    return {tell: name for tell, name in TRANSLITERATION_TELLS.items() if tell in (text or "")}


_FOREIGN_SCRIPT_PATTERN = re.compile(r"[؀-ۿﭐ-﷿ﹰ-﻿Ѐ-ӿ฀-๿]")


def stray_foreign_script_chars(text: str) -> list[str]:
    return _FOREIGN_SCRIPT_PATTERN.findall(text or "")


MAP_SYSTEM_PROMPT = """You are helping build a biweekly narrative trends report for a geopolitical news tracker. You will be given a compact list of daily report sections from a SHORT SPAN of consecutive days (not a full two weeks) - each already written by this same system as a short geopolitical write-up for its day, with an id, the date it belongs to, a topic label, and a short gist of its text.

Your task: group these daily write-ups by the actual real-world story/theme a reader would recognize as "the same unfolding situation" - not by matching the literal topic-label wording, which was generated independently each day and may phrase the same underlying story differently from one day to the next. A later pass will merge your groups with groups from other day-spans and write the final cross-period narrative - do NOT write any narrative prose yourself in this pass.

The goal is to surface which stories genuinely recur or develop across multiple days within this short span - a one-off item that never reappears is still its own topic (a single-day entry), not noise to discard.

Rules:
- Every section id you were given must appear in exactly one topic's section_ids - do not omit any, and do not place the same id in more than one topic.
- Group items from different days together whenever they are clearly about the same real-world story continuing or developing, even if the specific angle shifts somewhat day to day.
- If you are given no sections, call record_subwindow_topic_groups with an empty topics list."""

MAP_TOOL = {
    "name": "record_subwindow_topic_groups",
    "description": "Group this day-span's daily report sections into real-world story threads, without writing narrative prose.",
    "input_schema": {
        "type": "object",
        "properties": {
            "topics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "topic_label_en": {"type": "string"},
                        "section_ids": {"type": "array", "items": {"type": "integer"}},
                    },
                    "required": ["topic_label_en", "section_ids"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["topics"],
        "additionalProperties": False,
    },
    "strict": True,
}

REDUCE_SYSTEM_PROMPT = """You are merging several day-spans' worth of already-grouped story threads (from the previous pass) into ONE final list of real-world story threads for the full two-week period. Each input group has a label, the day-span it came from, and the section ids it contains.

Your task: merge groups from different day-spans that are clearly the SAME real-world story continuing or developing, under one final topic. A group that doesn't match any other should still become its own final topic - do not discard anything.

Rules:
- Every section id across all input groups must appear in exactly one final topic's section_ids - do not omit any, and do not place the same id in more than one final topic.
- Write a clear, final topic_label_en for each merged topic (you may keep an input label if it already fits, or write a better one that captures the merged story)."""

REDUCE_TOOL = {
    "name": "record_final_topic_groups",
    "description": "Merge day-span topic groups into the final cross-period topic list.",
    "input_schema": {
        "type": "object",
        "properties": {
            "topics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "topic_label_en": {"type": "string"},
                        "section_ids": {"type": "array", "items": {"type": "integer"}},
                    },
                    "required": ["topic_label_en", "section_ids"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["topics"],
        "additionalProperties": False,
    },
    "strict": True,
}

BIWEEKLY_STAGE2_SYSTEM_PROMPT = f"""You are a synthesis editor writing ONE section of a biweekly geopolitical trends report. Grouping already happened in an earlier pass: you are given a single recurring real-world story, already identified, together with EVERY one of its own daily write-ups across the two-week period - each one a short comparison already written and published by this same system for its own day, covering how that day's newspaper sources framed the story. You are not going back to the original newspaper articles - the daily write-ups themselves are your only source material.

Your task is fundamentally different from a daily cross-source comparison: it is a cross-TIME comparison of the SAME topic - and it must read as an analyst's brief, not a chronological narrative. Write in exactly this three-part structure, in order:

1. CONCLUSION FIRST (1-2 sentences, always first): state directly what changed in how this story was covered or perceived over the period - the starting framing compared with the latest framing. This is the single most important sentence you write - lead with it, do not build up to it.
2. SELECTED EVIDENCE (2-3 examples only, chosen for how well they illustrate the conclusion - NOT a day-by-day walkthrough): pick the few daily entries that best demonstrate the shift you just stated. Naming 2-3 specific dates/sources as evidence is correct; describing every single daily entry in sequence is not - skip entries that do not add new evidence for your conclusion, even if that means skipping most of the days this topic appeared on.
3. FRAMING DIFFERENCE (at most 1 sentence, only if one is genuinely clear): a single closing sentence on how sources or countries differed in their framing, if and only if there is a clear difference - omit this sentence entirely rather than invent one.

Do NOT narrate "the story began... then on day X... then on day Y... then finally...". Do NOT attempt to mention every daily entry you were given - selecting is part of the task, not a shortcut around it. A reader should get the conclusion in the first sentence, not after working through a timeline.

Date-anchoring (critical): each daily entry you are given is labeled with its own exact calendar date. Some of that daily text may contain relative time language from when it was originally written ("today", "this week", "yesterday", etc.) - any such phrase refers ONLY to that entry's own labeled date, never to any other date, and never to "now" or to the end of the two-week period. In your OWN narrative, always use explicit absolute dates (for example "by September 11" or "in the following days, through September 14") - never write "today", "this week", "recently", or any other relative-time phrase yourself, since a biweekly report has no single fixed "today" for the reader.

Reference sources by name only - never by any internal id or page number. Newspaper names: whenever you refer to a source by name, you must use EXACTLY one of these forms, in their original Latin script - never transliterate, translate, abbreviate, or mix scripts, in any language: "The Guardian", "The Daily Telegraph", "Süddeutsche Zeitung", "Die Welt", "The New York Times International", "The Wall Street Journal", "Los Angeles Times", "USA Today", "The Washington Post", "The Economist", "Der Spiegel". This applies identically inside Hebrew and German text - a Latin-script proper name is never rendered in Hebrew letters or Germanized.

Write natural, fluent prose in each language conveying the same substantive content - not a mechanical translation of one language into another; compose each of comparison_text_he/en/de independently from the same source material.

Hebrew grammar: comparison_text_he must be grammatically correct, standard Hebrew. Pay particular attention to gender agreement between numbers and the nouns they modify (e.g. "שתי כתבות" not "שני כתבות"). The Hebrew word for "drone" is "רחפן" (plural "רחפנים") - never the transliteration "דרון"/"דרונים". Reread each Hebrew sentence for this kind of error before finalizing it.

German: topic_label_de and comparison_text_de must read as if written natively in German by a professional journalist, in the same formal-but-readable register (Hochsprache) as this real excerpt of the project's established German house style: "{_GERMAN_STYLE_ANCHOR}". Pay particular attention to German article/adjective/case agreement and noun-number agreement; reread each German sentence for this kind of error before finalizing it.

topic_label_he/en/de are each a short section heading for this story, in their own language - not a translation of one another, and not identical to any single day's own daily label (which only described that one day's angle).

Call record_biweekly_topic exactly once with topic_label_he, topic_label_en, topic_label_de, comparison_text_he, comparison_text_en, and comparison_text_de."""

BIWEEKLY_COMPARE_TOOL = {
    "name": "record_biweekly_topic",
    "description": "Record this topic's cross-time narrative for the biweekly report, in all three languages.",
    "input_schema": {
        "type": "object",
        "properties": {
            "topic_label_he": {"type": "string"},
            "topic_label_en": {"type": "string"},
            "topic_label_de": {"type": "string"},
            "comparison_text_he": {"type": "string"},
            "comparison_text_en": {"type": "string"},
            "comparison_text_de": {"type": "string"},
        },
        "required": [
            "topic_label_he", "topic_label_en", "topic_label_de",
            "comparison_text_he", "comparison_text_en", "comparison_text_de",
        ],
        "additionalProperties": False,
    },
    "strict": True,
}

OVERVIEW_SYSTEM_PROMPT = """You are writing the short opening paragraph of a biweekly geopolitical trends report, AFTER every individual topic section has already been written. You are given the list of topics included in this edition, ordered by how many distinct newspaper sources covered them over the two weeks, each with its day-span and a one-line gist.

Write a brief, genuinely informative overview - 2-3 sentences, in each of Hebrew/English/German - that tells the reader what stood out across the period as a whole, and names any real pattern connecting two or more topics (for example several topics converging on the same region, or a shared theme like escalation/domestic-politics-under-pressure) if one is actually there. Do not simply restate the topic list. If there is no genuine cross-topic pattern, say so plainly rather than inventing one - name the one or two most significant individual topics instead.

Hebrew terminology: the Hebrew word for "drone" is "רחפן" (plural "רחפנים") - never the transliteration "דרון"/"דרונים".

Call record_overview exactly once with overview_he, overview_en, overview_de."""

OVERVIEW_TOOL = {
    "name": "record_overview",
    "description": "Record the biweekly report's short opening overview paragraph, in all three languages.",
    "input_schema": {
        "type": "object",
        "properties": {
            "overview_he": {"type": "string"},
            "overview_en": {"type": "string"},
            "overview_de": {"type": "string"},
        },
        "required": ["overview_he", "overview_en", "overview_de"],
        "additionalProperties": False,
    },
    "strict": True,
}


def gist_of(comparison_text_en: str) -> str:
    text = (comparison_text_en or "").strip()
    return text[:GIST_CHARS] + ("..." if len(text) > GIST_CHARS else "")


def format_sections_compact(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        lines.append(
            f"[id={r['id']}] [{r['report_date']}] {r['topic_label_en']}\n  gist: {gist_of(r['comparison_text_en'])}"
        )
    return "\n".join(lines)


def count_tokens(client, system_prompt: str, user_content: str) -> int:
    resp = client.messages.count_tokens(
        model=MODEL,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    return resp.input_tokens


def build_windows(client, dates: list[str], rows_by_date: dict[str, list[dict]]) -> list[list[str]]:
    """Token-budgeted sub-windows of consecutive dates (~45K tokens each),
    same compact-item philosophy as synthesize.py's format_articles_compact()
    - label + a short gist, not full prose."""
    windows = []
    current_dates: list[str] = []
    for d in dates:
        trial_dates = current_dates + [d]
        rows = []
        for td in trial_dates:
            rows.extend(rows_by_date[td])
        text = format_sections_compact(rows)
        tokens = count_tokens(client, MAP_SYSTEM_PROMPT, text)
        if tokens > TARGET_TOKENS_PER_MAP_WINDOW and current_dates:
            windows.append(list(current_dates))
            current_dates = [d]
        else:
            current_dates = trial_dates
    if current_dates:
        windows.append(list(current_dates))
    return windows


def call_map_once(client, dates, rows, user_content):
    with client.messages.stream(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        system=MAP_SYSTEM_PROMPT,
        tools=[MAP_TOOL],
        tool_choice={"type": "tool", "name": "record_subwindow_topic_groups"},
        messages=[{"role": "user", "content": user_content}],
    ) as stream:
        response = stream.get_final_message()
    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    topics = tool_use.input.get("topics", []) if tool_use else []
    usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    return topics, usage


def run_map(client, window_idx, dates, rows_by_date):
    rows = []
    for d in dates:
        rows.extend(rows_by_date[d])
    valid_ids = {r["id"] for r in rows}
    text = format_sections_compact(rows)
    user_content = f"Day-span {dates[0]}..{dates[-1]} ({len(rows)} section(s) total):\n\n{text}"

    topics, usage = call_map_once(client, dates, rows, user_content)
    missing, duplicated, ratio = compute_stage1_problem_ratio(topics, valid_ids, key="section_ids")
    usages = [usage]
    retries = 0

    if ratio > BIWEEKLY_GROUPING_RATIO_THRESHOLD:
        retries += 1
        print(f"  [map window {window_idx}] {dates[0]}..{dates[-1]}: {len(missing)} missing + "
              f"{len(duplicated)} duplicated ({ratio:.1%}) exceeds {BIWEEKLY_GROUPING_RATIO_THRESHOLD:.0%} - retrying once.")
        retry_topics, retry_usage = call_map_once(client, dates, rows, user_content)
        usages.append(retry_usage)
        retry_missing, retry_duplicated, retry_ratio = compute_stage1_problem_ratio(retry_topics, valid_ids, key="section_ids")
        if retry_ratio < ratio:
            topics, missing, duplicated, ratio = retry_topics, retry_missing, retry_duplicated, retry_ratio
            print(f"    retry improved ({ratio:.1%}) - using the retry result.")
        else:
            print(f"    retry did not improve - keeping the original grouping.")

    total_usage = {
        "input_tokens": sum(u["input_tokens"] for u in usages),
        "output_tokens": sum(u["output_tokens"] for u in usages),
    }
    print(f"  [map window {window_idx}] {dates[0]}..{dates[-1]} ({len(rows)} sections) -> "
          f"{len(topics)} topic(s), final: {len(missing)} missing, {len(duplicated)} duplicated")
    return topics, total_usage, retries


def call_reduce_once(client, user_content):
    with client.messages.stream(
        model=MODEL,
        max_tokens=24000,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        system=REDUCE_SYSTEM_PROMPT,
        tools=[REDUCE_TOOL],
        tool_choice={"type": "tool", "name": "record_final_topic_groups"},
        messages=[{"role": "user", "content": user_content}],
    ) as stream:
        response = stream.get_final_message()
    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    topics = tool_use.input.get("topics", []) if tool_use else []
    usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    if response.stop_reason != "tool_use":
        print(f"    [reduce call] non-tool_use stop_reason: {response.stop_reason!r} "
              f"({'got' if tool_use else 'no'} tool_use block, {len(topics)} topic(s) recovered)")
    return topics, usage


def run_reduce(client, map_results, sections_by_id):
    lines = []
    for window_label, topics in map_results:
        for t in topics:
            dates_covered = sorted({sections_by_id[i]["report_date"] for i in t["section_ids"] if i in sections_by_id})
            first_id = t["section_ids"][0] if t["section_ids"] else None
            gist = gist_of(sections_by_id[first_id]["comparison_text_en"]) if first_id in sections_by_id else ""
            lines.append(
                f"day-span={window_label} | label: {t['topic_label_en']}\n"
                f"  dates covered: {', '.join(dates_covered)}\n"
                f"  section_ids: {t['section_ids']}\n"
                f"  gist: {gist}"
            )
    user_content = f"Day-span groups to merge ({len(lines)} total):\n\n" + "\n\n".join(lines)

    tokens = count_tokens(client, REDUCE_SYSTEM_PROMPT, user_content)
    print(f"  [reduce] input: {len(lines)} day-span topic group(s), {tokens} tokens")

    valid_ids = set(sections_by_id.keys())
    topics, usage = call_reduce_once(client, user_content)
    missing, duplicated, ratio = compute_stage1_problem_ratio(topics, valid_ids, key="section_ids")
    usages = [usage]
    retries = 0

    if ratio > BIWEEKLY_GROUPING_RATIO_THRESHOLD:
        retries += 1
        print(f"  [reduce] {len(missing)} missing + {len(duplicated)} duplicated ({ratio:.1%}) exceeds "
              f"{BIWEEKLY_GROUPING_RATIO_THRESHOLD:.0%} - retrying once.")
        retry_topics, retry_usage = call_reduce_once(client, user_content)
        usages.append(retry_usage)
        retry_missing, retry_duplicated, retry_ratio = compute_stage1_problem_ratio(retry_topics, valid_ids, key="section_ids")
        if retry_ratio < ratio:
            topics, missing, duplicated, ratio = retry_topics, retry_missing, retry_duplicated, retry_ratio
            print(f"    retry improved ({ratio:.1%}) - using the retry result.")
        else:
            print(f"    retry did not improve - keeping the original grouping.")

    total_usage = {
        "input_tokens": sum(u["input_tokens"] for u in usages),
        "output_tokens": sum(u["output_tokens"] for u in usages),
    }
    print(f"  [reduce] -> {len(topics)} final topic(s), final: {len(missing)} missing, {len(duplicated)} duplicated")
    return topics, total_usage, retries


def run_stage1(client, conn, start: str, end: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, report_date, topic_label_en, comparison_text_en
        FROM report_sections
        WHERE report_date BETWEEN ? AND ? AND category != 'additional_coverage'
        ORDER BY report_date, id
        """,
        (start, end),
    ).fetchall()
    rows = [dict(r) for r in rows]
    sections_by_id = {r["id"]: r for r in rows}
    rows_by_date: dict[str, list[dict]] = {}
    for r in rows:
        rows_by_date.setdefault(r["report_date"], []).append(r)
    dates = sorted(rows_by_date.keys())
    print(f"Biweekly stage 1: {len(rows)} non-fallback sections across {len(dates)} day(s) ({start}..{end}).")
    if not rows:
        return []

    windows = build_windows(client, dates, rows_by_date)
    print(f"  built {len(windows)} map window(s).")

    map_results = []
    for i, window_dates in enumerate(windows, 1):
        topics, usage, retries = run_map(client, i, window_dates, rows_by_date)
        map_results.append((f"W{i}({window_dates[0]}..{window_dates[-1]})", topics))

    print("  running reduce...")
    final_topics, usage, retries = run_reduce(client, map_results, sections_by_id)

    enriched = []
    for t in final_topics:
        dates_covered = sorted({sections_by_id[i]["report_date"] for i in t["section_ids"] if i in sections_by_id})
        enriched.append({
            "topic_label_en": t["topic_label_en"],
            "n_distinct_days": len(dates_covered),
            "dates_covered": dates_covered,
            "section_ids": t["section_ids"],
        })
    return enriched


def load_topics_for_stage2(conn, stage1_topics: list[dict], min_days: int = MIN_DISTINCT_DAYS) -> list[dict]:
    topics = [t for t in stage1_topics if t["n_distinct_days"] >= min_days]
    for t in topics:
        secs = t["section_ids"]
        placeholders = ",".join("?" * len(secs))
        rows = conn.execute(
            f"""
            SELECT DISTINCT a.newspaper
            FROM report_section_articles rsa
            JOIN articles a ON a.id = rsa.article_id
            WHERE rsa.section_id IN ({placeholders})
            """,
            secs,
        ).fetchall()
        t["distinct_sources"] = sorted(r["newspaper"] for r in rows)
        t["n_sources"] = len(t["distinct_sources"])
    topics.sort(key=lambda t: -t["n_sources"])
    return topics


def load_topic_days(conn, topic: dict) -> list[dict]:
    secs = topic["section_ids"]
    placeholders = ",".join("?" * len(secs))
    rows = conn.execute(
        f"""
        SELECT id, report_date, topic_label_en, comparison_text_en
        FROM report_sections
        WHERE id IN ({placeholders})
        ORDER BY report_date
        """,
        secs,
    ).fetchall()
    return [dict(r) for r in rows]


def format_topic_days(days: list[dict]) -> str:
    blocks = []
    for i, d in enumerate(days, 1):
        blocks.append(
            f"[DATE: {d['report_date']}] (appearance {i} of {len(days)} for this topic)\n"
            f"Daily label that day: {d['topic_label_en']}\n"
            f'Daily text that day: "{d["comparison_text_en"]}"'
        )
    return "\n\n".join(blocks)


def write_biweekly_topic(client, topic: dict, days: list[dict], feedback: str = "") -> tuple[dict, dict]:
    tier = depth_tier(topic["n_distinct_days"])
    days_text = format_topic_days(days)
    feedback_block = f"\n{feedback}\n" if feedback else ""
    user_content = (
        f"Working topic label (from the clustering pass, for reference only - refine it yourself): "
        f"{topic['topic_label_en']}\n"
        f"This topic appears on {topic['n_distinct_days']} of the 14 days in the period, "
        f"drawn from {topic['n_sources']} distinct newspaper(s) over that span.\n\n"
        f"{DEPTH_INSTRUCTIONS[tier]}\n"
        f"{feedback_block}\n"
        f"Daily entries in chronological order ({len(days)} total):\n\n{days_text}"
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=[{"type": "text", "text": BIWEEKLY_STAGE2_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        tools=[BIWEEKLY_COMPARE_TOOL],
        tool_choice={"type": "tool", "name": "record_biweekly_topic"},
        messages=[{"role": "user", "content": user_content}],
    )
    tool_use = next(b for b in response.content if b.type == "tool_use")
    result = dict(tool_use.input)
    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
    }
    return result, usage


def write_biweekly_topic_with_retry(client, topic: dict, days: list[dict]):
    """Three independent guards feed the same single retry (attempt 0 only):
    _looks_suspicious (placeholder/garbage output -> drop on repeat failure),
    over_ceiling_langs (word-count over tier ceiling -> keep-and-flag on
    repeat failure), hebrew_newspaper_violations/stray_foreign_script_chars
    (newspaper name not in Latin script -> drop on repeat failure). See
    PROJECT_LOG 4.82/4.83 for why each was added."""
    usage_totals = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    tier = depth_tier(topic["n_distinct_days"])
    feedback = ""
    last_over = {}
    for attempt in range(2):
        try:
            result, usage = write_biweekly_topic(client, topic, days, feedback=feedback)
        except Exception as exc:
            print(f"  topic '{topic['topic_label_en']}' attempt {attempt + 1} failed: {exc}")
            continue
        for k in usage_totals:
            usage_totals[k] += usage.get(k, 0)

        suspicious_langs = [
            lang for lang in ("he", "en", "de")
            if _looks_suspicious(result[f"comparison_text_{lang}"])
        ]
        over = over_ceiling_langs(result, tier)
        last_over = over

        he_fields = result["comparison_text_he"] + " " + result["topic_label_he"]
        newspaper_hits = hebrew_newspaper_violations(he_fields)
        foreign_chars = stray_foreign_script_chars(he_fields)

        if (suspicious_langs or over or newspaper_hits or foreign_chars) and attempt == 0:
            reasons = []
            if suspicious_langs:
                reasons.append(f"suspicious output in: {', '.join(suspicious_langs)}")
            if over:
                reasons.append("over the " + f"{WORD_CEILINGS[tier]}-word ceiling: "
                                + ", ".join(f"{lang}={n}w" for lang, n in over.items()))
            if newspaper_hits or foreign_chars:
                reasons.append(f"Hebrew newspaper-name violation: {list(newspaper_hits.keys())}, "
                                f"foreign chars: {set(foreign_chars)}")
            print(f"  topic '{topic['topic_label_en']}' attempt {attempt + 1}: {'; '.join(reasons)} - retrying once.")
            feedback_parts = []
            if over:
                feedback_parts.append(
                    "Your previous attempt exceeded the word ceiling for this tier: "
                    + ", ".join(f"{lang} was {n} words (limit {WORD_CEILINGS[tier]})" for lang, n in over.items())
                    + ". Cut it down to fit within the limit in each of those languages, keeping the "
                    "conclusion-first structure (do not pad the other languages to match - each has its own limit)."
                )
            if newspaper_hits or foreign_chars:
                corrections = "; ".join(f'"{tell}" should have been "{name}"' for tell, name in newspaper_hits.items())
                feedback_parts.append(
                    "Your previous attempt violated the newspaper-name rule in comparison_text_he/"
                    "topic_label_he: it rendered a newspaper name in Hebrew letters instead of keeping "
                    "it in its exact Latin-script form. "
                    + (f"Specifically: {corrections}. " if corrections else "")
                    + "Rewrite the Hebrew text so every newspaper reference uses its exact Latin-script "
                    "name verbatim (e.g. \"Süddeutsche Zeitung\", \"The Wall Street Journal\") embedded "
                    "directly inside the Hebrew sentence - never transliterated, never in Hebrew letters."
                )
            feedback = " ".join(feedback_parts)
            continue

        if suspicious_langs:
            print(f"  topic '{topic['topic_label_en']}' still suspicious after retry - dropping.")
            return None, usage_totals, {}
        if newspaper_hits or foreign_chars:
            print(f"  topic '{topic['topic_label_en']}' still has a newspaper-name violation after retry - dropping.")
            return None, usage_totals, {}
        if over:
            print(f"  topic '{topic['topic_label_en']}' still over ceiling after retry "
                  f"({', '.join(f'{lang}={n}w' for lang, n in over.items())}) - keeping anyway, flagged.")
        return result, usage_totals, over
    return None, usage_totals, last_over


def write_overview(client, topics: list[dict]) -> tuple[dict, dict]:
    lines = [f"- {t['topic_label_en']} ({t['n_distinct_days']}d, {t['n_sources']} src)" for t in topics]
    user_content = "Topics in this edition, by source-breadth:\n\n" + "\n".join(lines)
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=OVERVIEW_SYSTEM_PROMPT,
        tools=[OVERVIEW_TOOL],
        tool_choice={"type": "tool", "name": "record_overview"},
        messages=[{"role": "user", "content": user_content}],
    )
    tool_use = next(b for b in response.content if b.type == "tool_use")
    result = dict(tool_use.input)
    usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    return result, usage


def run_stage2(client, conn, topics: list[dict]) -> tuple[dict, list[dict]]:
    for t in topics:
        t["_days"] = load_topic_days(conn, t)

    tier_counts = {"deep": 0, "developed": 0, "concise": 0}
    for t in topics:
        tier_counts[depth_tier(t["n_distinct_days"])] += 1
    print(f"Stage 2: writing {len(topics)} topic(s). Depth tiers: {tier_counts}")

    results: dict[str, dict] = {}
    failed = []

    first = topics[0]
    print(f"  cache-warming with: {first['topic_label_en']}")
    result, usage, over = write_biweekly_topic_with_retry(client, first, first["_days"])
    if result is None:
        failed.append(first["topic_label_en"])
    else:
        results[first["topic_label_en"]] = result

    remaining = topics[1:]
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        future_to_topic = {
            executor.submit(write_biweekly_topic_with_retry, client, t, t["_days"]): t for t in remaining
        }
        for future in as_completed(future_to_topic):
            t = future_to_topic[future]
            result, usage, over = future.result()
            if result is None:
                failed.append(t["topic_label_en"])
            else:
                results[t["topic_label_en"]] = result

    if failed:
        print(f"  {len(failed)} topic(s) dropped after failing their guard twice: {failed}")

    kept_topics = [t for t in topics if t["topic_label_en"] in results]
    for t in kept_topics:
        t["result"] = results[t["topic_label_en"]]

    print("  writing overview...")
    overview, _ = write_overview(client, kept_topics)
    return overview, kept_topics


def write_period_to_db(conn, start: str, end: str, overview: dict, topics: list[dict], force: bool) -> int:
    if biweekly_period_exists(conn, end):
        if not force:
            raise SystemExit(f"Period ending {end} already exists - pass --force to overwrite.")
        delete_biweekly_period(conn, end)

    period_id = insert_biweekly_period(
        conn, start, end,
        overview["overview_he"], overview["overview_en"], overview["overview_de"],
        datetime.now(timezone.utc).isoformat(),
    )
    for sort_order, t in enumerate(topics):
        r = t["result"]
        topic_id = insert_biweekly_topic(
            conn, period_id,
            r["topic_label_he"], r["topic_label_en"], r["topic_label_de"],
            r["comparison_text_he"], r["comparison_text_en"], r["comparison_text_de"],
            t["n_distinct_days"], t["n_sources"], sort_order,
        )
        # dict.fromkeys() de-dup - see scripts/migrate_biweekly_dryrun_to_db.py
        # for why a section id can legitimately repeat within one topic's list.
        for section_id in dict.fromkeys(t["section_ids"]):
            link_biweekly_topic_section(conn, topic_id, section_id)
    return period_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Biweekly narrative-trends report (map-reduce + narrative writing).")
    parser.add_argument("--start", default=None, help="Period start, YYYY-MM-DD. Omit with --end to auto-detect today's closing period.")
    parser.add_argument("--end", default=None, help="Period end, YYYY-MM-DD.")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing period for this end date.")
    args = parser.parse_args()

    conn = get_connection()
    init_db(conn)

    if args.start and args.end:
        start, end = args.start, args.end
    elif not args.start and not args.end:
        due = period_closing_on(date.today())
        if due is None:
            print(f"Today ({date.today().isoformat()}) is not the closing date of a biweekly period - nothing to do.")
            conn.close()
            return 0
        start, end = due[0].isoformat(), due[1].isoformat()
        print(f"Auto-detected closing period: {start}..{end}")
    else:
        parser.error("--start and --end must be given together.")
        return 2

    if biweekly_period_exists(conn, end) and not args.force:
        print(f"Period ending {end} already exists - nothing to do (pass --force to overwrite).")
        conn.close()
        return 0

    client = anthropic.Anthropic()

    stage1_topics = run_stage1(client, conn, start, end)
    if not stage1_topics:
        print("No sections found for this period - nothing to synthesize.")
        conn.close()
        return 0

    topics = load_topics_for_stage2(conn, stage1_topics)
    print(f"{len(topics)} topic(s) cleared the >={MIN_DISTINCT_DAYS}-day inclusion threshold.")
    if not topics:
        print("No topic cleared the inclusion threshold - no report for this period.")
        conn.close()
        return 0

    overview, kept_topics = run_stage2(client, conn, topics)

    period_id = write_period_to_db(conn, start, end, overview, kept_topics, args.force)
    print(f"Wrote biweekly period id={period_id} ({start}..{end}), {len(kept_topics)} topic(s), to tracker.db.")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
