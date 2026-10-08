"""One-off dry-run (NOT a pipeline stage, NOT wired into daily_autorun.py or any
production script) for the planned biweekly narrative-trends report's Stage 2:
writing the actual cross-day narrative for each topic that cleared Stage 1's
map-reduce clustering (see biweekly_stage1_dryrun.py) and the >=5-day inclusion
threshold.

Reuses the daily pipeline's proven Stage-2 architecture as closely as possible
(synthesize.py's write_topic_comparison/STAGE2_SYSTEM_PROMPT/COMPARE_TOOL) -
same shape: one call per topic, forced tool-choice, a single ephemeral-cached
system prompt shared across all calls, cache-warmed by firing the first topic
alone before fanning the rest out across a thread pool. What's different is the
"axis of comparison": daily Stage 2 compares SOURCES on the SAME day; this
compares the SAME topic's coverage ACROSS DAYS - the input per topic is that
topic's own chronological sequence of already-published daily write-ups (full
comparison_text_en, not the stage-1 gist), each labeled with its exact date so
relative phrasing in the source text ("today", "this week") never leaks into
the biweekly narrative as if it meant something else.

Depth is tiered by how many distinct days the topic covers (not a uniform
target for every topic, per the editorial policy this dry-run is testing).
Revised 2026-10-07 after reviewing the first draft: the original "trace the
arc, describe each phase" instruction produced a full chronological walk-
through per topic (a "dissertation", not an analyst brief) regardless of the
paragraph-count target. Replaced with a strict conclusion-first structure
(state the conclusion, then 2-3 SELECTED examples, not a day-by-day account)
plus a hard per-language word ceiling that is actually measured after writing
and retried once if exceeded - not just a style suggestion:
  deep       (>=8 days):   conclusion-first, 2-3 selected examples, <=140 words
  developed  (5-7 days):   conclusion-first, 2 selected examples,   <=100 words
  concise    (3-4 days):   conclusion-first, 1-2 selected examples, <=70 words
The inclusion threshold was also raised from >=3 to >=5 days in the same
revision (20 topics qualify under >=5, vs 58 under >=3) - so no topic
currently falls in the "concise" tier, but it's kept in code for when/if the
threshold changes again.

Writes nothing to the DB and publishes nothing - reads
scripts/output/biweekly_stage2_input_topics.json (produced by a companion
diagnostic step) and tracker.db, makes real (paid) Claude API calls (one per
topic + one overview call), and writes a plain-Markdown draft per language to
scripts/output/ for human review only.
"""
import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import anthropic
from dotenv import load_dotenv

from src.common.db import get_connection
from src.reporting.render import NEWSPAPER_DISPLAY_NAMES
from src.reporting.synthesize import _GERMAN_STYLE_ANCHOR, _looks_suspicious

load_dotenv()

MODEL = "claude-sonnet-5"
CONCURRENCY = 6
OUTPUT_DIR = Path(__file__).resolve().parent / "output"

# Finalized inclusion threshold (raised 2026-10-07 from the original >=3 after
# reviewing the P2 draft - see biweekly_stage1_dryrun.py / PROJECT_LOG for why).
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
    """Returns {lang: actual_word_count} for every comparison_text_{lang} that
    exceeds this topic's tier ceiling - empty dict if none do."""
    ceiling = WORD_CEILINGS[tier]
    over = {}
    for lang in ("he", "en", "de"):
        n = word_count(result[f"comparison_text_{lang}"])
        if n > ceiling:
            over[lang] = n
    return over


# Exact Latin-script forms the existing rule (already in both STAGE2_SYSTEM_PROMPT
# and BIWEEKLY_STAGE2_SYSTEM_PROMPT) requires - taken directly from render.py's
# NEWSPAPER_DISPLAY_NAMES, not re-typed by hand, so this can never silently
# drift from the canonical list.
APPROVED_NEWSPAPER_NAMES_LATIN = list(NEWSPAPER_DISPLAY_NAMES.values())

# Distinctive Hebrew-letter transliteration fragments that would only
# plausibly appear if comparison_text_he/topic_label_he violated that rule -
# built 2026-10-08 after finding the violation in BOTH a garbled form (mixed
# Arabic/Cyrillic characters - e.g. "זюддойчה צייטונג") and a clean-Hebrew
# form with no foreign characters at all (e.g. "זידה-צייטונג"), which a
# foreign-character check alone cannot catch. Verified against the live
# archive before relying on this: spot-checked real context in
# docs/he/report_2026-09-16_he.html confirmed every one of these fragments
# marks a genuine transliterated newspaper reference there too (not an
# unrelated word sense) - this is a real, separate, PRE-EXISTING production
# issue (38/46 live Hebrew reports affected), not a false-positive-prone
# guess. Each fragment targets a distinctive piece of one outlet's name;
# ambiguous standalone words that have an unrelated common meaning in Hebrew
# ("פוסט" = a generic "post", "וולט" = the electrical unit) are deliberately
# paired with an adjacent word instead of listed alone, to keep this precise.
TRANSLITERATION_TELLS = {
    "צייטונג": "Süddeutsche Zeitung",
    "שפיגל": "Der Spiegel",
    "טלגרף": "The Daily Telegraph",
    "גארדיין": "The Guardian",
    "גרדיאן": "The Guardian",
    "אקונומיסט": "The Economist",
    "ג'ורנל": "The Wall Street Journal",
    "ג'רנל": "The Wall Street Journal",
    "וול סטריט": "The Wall Street Journal",
    "וושינגטון פוסט": "The Washington Post",
    "לוס אנג'לס": "Los Angeles Times",
    "טיימס": "Los Angeles Times / The New York Times International",
    "טודיי": "USA Today",
    "די וולט": "Die Welt",
}


def hebrew_newspaper_violations(text: str) -> dict[str, str]:
    """Returns {found_hebrew_fragment: correct_latin_name} for every
    transliteration tell present in `text` - empty dict if the text correctly
    keeps all newspaper references in Latin script. Catches both the garbled
    (mixed-script) and clean-Hebrew-letters forms of the same rule violation."""
    return {tell: name for tell, name in TRANSLITERATION_TELLS.items() if tell in (text or "")}


_FOREIGN_SCRIPT_PATTERN = re.compile(r"[؀-ۿﭐ-﷿ﹰ-﻿Ѐ-ӿ]")


def stray_foreign_script_chars(text: str) -> list[str]:
    """Arabic/Cyrillic characters have no legitimate place in Hebrew output -
    their presence is itself a strong signal of a garbled transliteration
    attempt, independent of whether it also matches a known TRANSLITERATION_TELLS
    fragment (a sufficiently mangled attempt might not match any fragment)."""
    return _FOREIGN_SCRIPT_PATTERN.findall(text or "")


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


def load_topics_from_stage1(stage1_path: Path, conn, min_days: int = MIN_DISTINCT_DAYS) -> tuple[list[dict], list[str]]:
    """Reads a biweekly_stage1_dryrun_*.json file directly (no separate
    hand-run intermediate file) - filters to the inclusion threshold and
    computes each topic's distinct-source count (the ordering metric), the
    same query previously run ad hoc by hand each time. This is the one place
    that makes this script a genuine reusable template rather than something
    that depends on a manual step outside any .py file."""
    with open(stage1_path, encoding="utf-8") as f:
        data = json.load(f)
    topics = [t for t in data["final_topics"] if t["n_distinct_days"] >= min_days]
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
    return topics, data["window"]


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
    """Same guard+retry SHAPE as synthesize.py's write_topic_comparison_with_retry()
    (_looks_suspicious() imported directly, not re-implemented) - one retry on
    attempt 0 if something is wrong, then give up. THREE independent checks
    feed the same single retry, added at different times for different reasons:

    1. _looks_suspicious() (too short, a bare number, a leftover tag fragment) -
       added after a real, isolated case where one topic wrote a full Hebrew
       paragraph but literally output the placeholder string '__SEE_ABOVE__'
       for comparison_text_en/de. Still suspicious after retry -> return None
       (dropped from the draft, same as daily Stage 2's fallback path).

    2. over_ceiling_langs() (word count over this topic's tier ceiling) - added
       2026-10-07 after a full dry-run read as a "dissertation" rather than an
       analyst brief regardless of the paragraph-count language in the prompt;
       a style suggestion alone wasn't enough, so this is code-measured after
       writing. The retry here is NOT blind - the retry prompt is told exactly
       which language(s) were how many words over. Still over after retry ->
       KEPT (not dropped - a few words over isn't malformed output) but
       flagged in the returned info so it's visible, not silently absorbed.

    3. hebrew_newspaper_violations()/stray_foreign_script_chars() - added
       2026-10-08 after finding comparison_text_he transliterating newspaper
       names into Hebrew letters instead of keeping them in Latin script, as
       the existing rule already requires - in both a garbled (mixed Arabic/
       Cyrillic characters) and a clean-Hebrew-letters form. Unlike check 2,
       this is a correctness-rule violation, not a style/length issue - still
       violating after retry -> return None (dropped), same as check 1."""
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
                reasons.append(
                    "over the "
                    f"{WORD_CEILINGS[tier]}-word ceiling: "
                    + ", ".join(f"{lang}={n}w" for lang, n in over.items())
                )
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
                    "conclusion-first structure (do not pad the other languages to match - each has its "
                    "own limit)."
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
            print(
                f"  topic '{topic['topic_label_en']}' still suspicious after retry "
                f"({', '.join(suspicious_langs)}) - treating as failed."
            )
            return None, usage_totals, {}, {}
        if newspaper_hits or foreign_chars:
            print(
                f"  topic '{topic['topic_label_en']}' still has a Hebrew newspaper-name violation after "
                f"retry ({list(newspaper_hits.keys())}, foreign chars: {set(foreign_chars)}) - treating as failed."
            )
            return None, usage_totals, {}, {}
        if over:
            print(
                f"  topic '{topic['topic_label_en']}' still over ceiling after retry "
                f"({', '.join(f'{lang}={n}w' for lang, n in over.items())}) - keeping anyway, flagged."
            )
        return result, usage_totals, over, newspaper_hits
    return None, usage_totals, last_over, {}


def write_overview(client, topics: list[dict]) -> tuple[dict, dict]:
    lines = []
    for t in topics:
        lines.append(f"- {t['topic_label_en']} ({t['n_distinct_days']}d, {t['n_sources']} src)")
    user_content = f"Topics in this edition, by source-breadth:\n\n" + "\n".join(lines)
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


def main():
    parser = argparse.ArgumentParser(description="Biweekly Stage 2 narrative dry-run.")
    parser.add_argument("--start", default="2026-09-03", help="Period start, YYYY-MM-DD (default: P2's start).")
    parser.add_argument("--end", default="2026-09-16", help="Period end, YYYY-MM-DD (default: P2's end).")
    parser.add_argument(
        "--only", default=None,
        help="Substring match against a topic's stage-1 topic_label_en - process only that one "
             "topic (e.g. for re-testing a single topic after a fix), skip the overview call and "
             "draft-file assembly entirely.",
    )
    args = parser.parse_args()
    period_suffix = f"{args.start}_{args.end}"
    stage1_path = OUTPUT_DIR / f"biweekly_stage1_dryrun_{period_suffix}.json"

    conn = get_connection()
    topics, window = load_topics_from_stage1(stage1_path, conn)

    if args.only:
        topics = [t for t in topics if args.only.lower() in t["topic_label_en"].lower()]
        if not topics:
            print(f"No topic matched --only {args.only!r}.")
            conn.close()
            return
        print(f"--only {args.only!r}: matched {len(topics)} topic(s): "
              f"{[t['topic_label_en'] for t in topics]}")
    else:
        print(f"Writing biweekly Stage 2 narrative for {len(topics)} topics "
              f"({window[0]}..{window[1]}, >={MIN_DISTINCT_DAYS}-day threshold)...")

    for t in topics:
        t["_days"] = load_topic_days(conn, t)
    conn.close()

    tier_counts = {"deep": 0, "developed": 0, "concise": 0}
    for t in topics:
        tier_counts[depth_tier(t["n_distinct_days"])] += 1
    print(f"Depth tiers: {tier_counts}")

    client = anthropic.Anthropic()

    results = {}
    failed = []
    total_usage = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}

    still_over = {}  # topic_label_en -> {lang: word_count} still over ceiling after retry

    if args.only:
        # Single-topic targeted re-test - no cache-warming/thread-pool needed.
        for t in topics:
            result, usage, over, _ = write_biweekly_topic_with_retry(client, t, t["_days"])
            for k in total_usage:
                total_usage[k] += usage.get(k, 0)
            if result is None:
                failed.append(t["topic_label_en"])
                print(f"  FAILED (still failing after retry - see reason above): {t['topic_label_en']}")
            else:
                results[t["topic_label_en"]] = result
                if over:
                    still_over[t["topic_label_en"]] = over
                print(f"  SUCCESS: {result['topic_label_en']}")
                print(f"    EN: {result['comparison_text_en'][:300]}")
                print(f"    HE: {result['comparison_text_he'][:200]}")
                print(f"    DE: {result['comparison_text_de'][:200]}")
        print(f"\n--only run complete: {len(results)} succeeded, {len(failed)} failed.")
        print(f"usage: {total_usage}")
        return

    # Cache-warm: fire the first topic alone so its ephemeral system-prompt
    # cache write completes before the rest fan out concurrently - same
    # pattern synthesize_day_two_stage() already uses for daily Stage 2.
    first = topics[0]
    print(f"  cache-warming with: {first['topic_label_en']}")
    result, usage, over, _ = write_biweekly_topic_with_retry(client, first, first["_days"])
    for k in total_usage:
        total_usage[k] += usage.get(k, 0)
    if result is None:
        failed.append(first["topic_label_en"])
        print(f"  FAILED (still failing after retry - see reason above): {first['topic_label_en']}")
    else:
        results[first["topic_label_en"]] = result
        if over:
            still_over[first["topic_label_en"]] = over

    remaining = topics[1:]
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        future_to_topic = {
            executor.submit(write_biweekly_topic_with_retry, client, t, t["_days"]): t for t in remaining
        }
        done = 1
        for future in as_completed(future_to_topic):
            t = future_to_topic[future]
            result, usage, over, _ = future.result()
            for k in total_usage:
                total_usage[k] += usage.get(k, 0)
            done += 1
            if result is None:
                failed.append(t["topic_label_en"])
                print(f"  [{done}/{len(topics)}] FAILED (still failing after retry - see reason above): {t['topic_label_en']}")
            else:
                results[t["topic_label_en"]] = result
                if over:
                    still_over[t["topic_label_en"]] = over
                print(f"  [{done}/{len(topics)}] wrote: {result['topic_label_en']}")

    if failed:
        print(f"\n{len(failed)} topic(s) failed after retry and were excluded from the draft: {failed}")
    # Keep only topics that actually produced a result, in their original order.
    topics = [t for t in topics if t["topic_label_en"] in results]

    print("\nWriting overview paragraph...")
    overview, overview_usage = write_overview(client, topics)
    total_usage["input_tokens"] += overview_usage["input_tokens"]
    total_usage["output_tokens"] += overview_usage["output_tokens"]

    print(f"\nTotal usage: {total_usage}")

    # --- actual word counts vs each topic's tier ceiling (the real test of
    # whether the retry enforces the limit or just asks nicely) ---
    print("\n--- actual word count (EN) vs tier ceiling, per topic ---")
    by_tier_words: dict[str, list[int]] = {"deep": [], "developed": [], "concise": []}
    for t in topics:
        tier = depth_tier(t["n_distinct_days"])
        n = word_count(results[t["topic_label_en"]]["comparison_text_en"])
        by_tier_words[tier].append(n)
        flag = " *** STILL OVER AFTER RETRY ***" if t["topic_label_en"] in still_over else ""
        print(f"  [{tier:9}] {n:3d}w / {WORD_CEILINGS[tier]:3d}w ceiling  -  {t['topic_label_en']}{flag}")
    print("\n--- summary by tier ---")
    for tier, counts in by_tier_words.items():
        if counts:
            ceiling = WORD_CEILINGS[tier]
            over_n = sum(1 for c in counts if c > ceiling)
            print(f"  {tier:10} n={len(counts):2d}  ceiling={ceiling:3d}  "
                  f"min={min(counts):3d}  mean={sum(counts)/len(counts):5.1f}  max={max(counts):3d}  "
                  f"over-ceiling={over_n}")
    if still_over:
        print(f"\n{len(still_over)} topic(s) still over ceiling after retry (kept, flagged): {still_over}")
    else:
        print("\nAll topics within their tier's word ceiling after at most one retry.")

    # --- assemble drafts ---
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    import datetime as _dt
    d0 = _dt.date.fromisoformat(window[0])
    d1 = _dt.date.fromisoformat(window[1])
    _MONTHS_EN = ["", "January", "February", "March", "April", "May", "June", "July",
                  "August", "September", "October", "November", "December"]
    _MONTHS_DE = ["", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
                  "August", "September", "Oktober", "November", "Dezember"]
    titles = {
        "he": f"דוח מגמות דו-שבועי (טיוטה) - {d0.day}.{d0.month}–{d1.day}.{d1.month}.{d1.year}",
        "en": f"Biweekly Trends Report (Draft) - {_MONTHS_EN[d0.month]} {d0.day}-{d1.day}, {d1.year}",
        "de": f"Zweiwöchentlicher Trendbericht (Entwurf) - {d0.day}.-{d1.day}. {_MONTHS_DE[d1.month]} {d1.year}",
    }
    for lang in ("he", "en", "de"):
        lines = [f"# {titles[lang]}", ""]
        lines.append(overview[f"overview_{lang}"])
        lines.append("")
        lines.append("---")
        for t in topics:
            r = results[t["topic_label_en"]]
            lines.append("")
            lines.append(f"## {r[f'topic_label_{lang}']}")
            lines.append(f"*({t['n_distinct_days']} of 14 days, {t['n_sources']} distinct source(s): "
                         f"{', '.join(t['distinct_sources'])})*")
            lines.append("")
            lines.append(r[f"comparison_text_{lang}"])
        out_path = OUTPUT_DIR / f"biweekly_draft_{lang}_{period_suffix}.md"
        out_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"wrote {out_path}")

    # raw data for inspection
    raw_path = OUTPUT_DIR / f"biweekly_stage2_dryrun_raw_{period_suffix}.json"
    raw_path.write_text(
        json.dumps(
            {
                "overview": overview,
                "topics": [
                    {**{k: v for k, v in t.items() if k != "_days"}, "result": results[t["topic_label_en"]]}
                    for t in topics
                ],
                "usage": total_usage,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {raw_path}")


if __name__ == "__main__":
    main()
