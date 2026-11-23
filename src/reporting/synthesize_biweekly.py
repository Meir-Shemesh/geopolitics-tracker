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
import hashlib
import os
from pathlib import Path
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[2]

import anthropic
import httpx2
from dotenv import load_dotenv

from src.common.biweekly import missing_published_days, period_closing_on
from src.reporting.text_checks import (  # one shared copy with the daily writer
    NEWSPAPER_NAME_TELLS,
    attached_prefix_repairs,
    fix_attached_prefixes,
    foreign_script_chars,
    hebrew_newspaper_name_tells,
    latin_name_form_counts,
    problem_kind,
    problems_feedback,
    writer_problems,
)
from src.common.db import (
    print_usage_summary,
    record_api_usage,
    record_biweekly_reduce_run,
    usage_marker,
    biweekly_period_exists,
    delete_biweekly_period,
    get_connection,
    get_report_dates_in_range,
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

# The reduce call writes every final topic (label + section ids) in one tool_use block. Its output grows with the
# number of day-span groups: 21,033 output tokens at 129K input (22.10) and 23,595 at 137K (29.10) against the old
# ceiling of 24,000; on 5.11 (150K input, 878 groups) the ceiling was hit twice. The model allows far more (128K per
# the models overview) and the call already streams, so only the ceiling moves - prompt, tool schema, effort and the
# grouping are untouched. Billing is per token actually produced, so a higher ceiling costs nothing when unused.
REDUCE_MAX_TOKENS = 64000
REDUCE_NEAR_CEILING_RATIO = 0.75


# Exit codes (2 = unpublished days, see main()). Anything non-zero means "no period row was written".
EXIT_REDUCE_FAILED = 3
EXIT_NO_TOPICS = 4


def reduce_ceiling_warning(output_tokens: int, max_tokens: int = REDUCE_MAX_TOKENS) -> str | None:
    """Same idea as synthesize.stage1_ceiling_warning(): a heads-up, never a change in behaviour."""
    if output_tokens >= REDUCE_NEAR_CEILING_RATIO * max_tokens:
        return (f"REDUCE OUTPUT NEAR CEILING: {output_tokens} of {max_tokens} tokens "
                f"({output_tokens / max_tokens:.0%}) - one more heavy period may truncate the reduce")
    return None


class ReduceFailedError(RuntimeError):
    """The reduce pass produced no usable grouping (truncated at the output ceiling, or no topics at all). Raised
    instead of returning an empty list, so nothing downstream can mistake it for 'no sections' and nothing is
    checkpointed or written."""

# ---------------------------------------------------------------------------
# Resilience (2026-10-15, PROJECT_LOG 4.100): the first live overnight run died
# 9 minutes in, in the middle of the reduce call's streaming response, with a raw
# httpx2.ReadError (WinError 10054) - after all three map calls had been paid
# for and with nothing persisted. Two additions, neither changes the grouping
# logic: (1) retry transient transport errors with backoff around every API
# call; (2) checkpoint map/reduce results to disk so a later failure never
# re-pays for them.
# ---------------------------------------------------------------------------
TRANSIENT_ERRORS = (
    anthropic.APIConnectionError,   # includes APITimeoutError
    httpx2.TransportError,          # the raw ReadError/ConnectError that escapes from a mid-stream failure
    ConnectionError,
    TimeoutError,
)
TRANSIENT_STATUS_CODES = (408, 409, 429, 500, 502, 503, 504, 529)
RETRY_BACKOFF_SECONDS = (15, 60)  # 3 attempts in total


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code in TRANSIENT_STATUS_CODES
    return isinstance(exc, TRANSIENT_ERRORS)


def call_with_retry(label: str, fn):
    """Runs fn(); on a transient network/overload error waits and tries again (3
    attempts total). Anything else - bad request, auth, a logic error - is
    raised immediately. The anthropic SDK's own max_retries only covers
    establishing a request, not a connection dropped mid-stream."""
    for attempt in range(len(RETRY_BACKOFF_SECONDS) + 1):
        try:
            return fn()
        except Exception as exc:
            if not _is_transient(exc) or attempt == len(RETRY_BACKOFF_SECONDS):
                raise
            delay = RETRY_BACKOFF_SECONDS[attempt]
            print(f"    [{label}] transient error ({type(exc).__name__}: {str(exc)[:120]}) - "
                  f"retry {attempt + 1}/{len(RETRY_BACKOFF_SECONDS)} in {delay}s", flush=True)
            time.sleep(delay)


_USAGE_LOCK = threading.Lock()
USAGE = {"calls": 0, "input": 0, "output": 0, "cache_create": 0, "cache_read": 0}
# Prices as stated in the request ($ per million tokens), not independently verified.
PRICE_IN, PRICE_OUT = 2.00, 10.00


def record_usage(usage, stage: str = "biweekly") -> None:
    record_api_usage(stage, MODEL, usage)  # persistent record (api_usage); the counters below are this process's summary
    with _USAGE_LOCK:
        USAGE["calls"] += 1
        USAGE["input"] += getattr(usage, "input_tokens", 0) or 0
        USAGE["output"] += getattr(usage, "output_tokens", 0) or 0
        USAGE["cache_create"] += getattr(usage, "cache_creation_input_tokens", 0) or 0
        USAGE["cache_read"] += getattr(usage, "cache_read_input_tokens", 0) or 0


def usage_summary(label: str) -> str:
    u = USAGE
    cost = (u["input"] + 1.25 * u["cache_create"] + 0.10 * u["cache_read"]) / 1e6 * PRICE_IN + u["output"] / 1e6 * PRICE_OUT
    return (f"[usage {label}] {u['calls']} call(s) completed in this process: input {u['input']:,}, output {u['output']:,} "
            f"(thinking included), cache-write {u['cache_create']:,}, cache-read {u['cache_read']:,} "
            f"-> ~${cost:.2f} at ${PRICE_IN:g}/${PRICE_OUT:g} per Mtok (calls that failed mid-stream are not counted)")


CHECKPOINT_DIR = PROJECT_ROOT / "data" / "processed" / "biweekly_checkpoints"


def _content_key(*parts) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(json.dumps(part, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def _checkpoint_path(start: str, end: str, kind: str, key: str) -> Path:
    return CHECKPOINT_DIR / f"{start}_{end}_{kind}_{key}.json"


def load_checkpoint(path: Path):
    """A missing, unreadable or half-written checkpoint is simply 'no checkpoint'."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # An empty topic list is never a valid map/reduce result; the 5.11 run checkpointed one after a truncated
        # reduce, which would make every later run "reuse" it and fail again without calling the API.
        return data if isinstance(data, dict) and data.get("topics") else None
    except (OSError, ValueError):
        return None


def save_checkpoint(path: Path, topics: list, usage: dict, retries: int) -> None:
    try:
        CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"topics": topics, "usage": usage, "retries": retries,
                                   "saved_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:  # a checkpoint is an optimisation; never fail the run over it
        print(f"    (warning: could not write checkpoint {path.name}: {exc})")


def clear_checkpoints(start: str, end: str) -> int:
    n = 0
    if CHECKPOINT_DIR.exists():
        for f in CHECKPOINT_DIR.glob(f"{start}_{end}_*.json"):
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
    return n

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
        "This topic spans a large majority of the two-week period (a 'deep' topic), "
        "write up to 2-3 selected examples (not a day-by-day account) illustrating your "
        f"conclusion. Hard limit: {WORD_CEILINGS['deep']} words for comparison_text_he/en/de "
        "each, this is measured after you write and you will be asked to cut it down if "
        "you exceed it, so budget your words accordingly rather than writing long and "
        "expecting it to be trimmed later."
    ),
    "developed": (
        "This topic spans a meaningful stretch of the two-week period (a 'developed' "
        "topic, not the most dominant but a real recurring story), use up to 2 selected "
        f"examples. Hard limit: {WORD_CEILINGS['developed']} words for comparison_text_he/en/de "
        "each, measured after you write."
    ),
    "concise": (
        "This topic is close to the inclusion threshold (a 'concise' topic), use at "
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


# A text 1-10% over its ceiling is accepted without a retry (logged). On 12.11 the first attempts of the Iran/Hormuz topic
# (de=141 words against 140) and of the Venezuela topic (en=101 against 100) were rejected for that alone, and the rewrite
# then failed another guard and the topics were dropped. The ceiling in the prompt is unchanged: the model is still told the
# hard limit, and a text more than 10% over (or still over after the retry) is handled exactly as before.
WORD_CEILING_TOLERANCE = 0.10


def over_ceiling_langs(result: dict, tier: str, tolerance: float = 0.0) -> dict[str, int]:
    """Languages whose comparison text has more words than the tier ceiling (times 1+tolerance)."""
    limit = int(WORD_CEILINGS[tier] * (1 + tolerance))
    over = {}
    for lang in ("he", "en", "de"):
        n = word_count(result[f"comparison_text_{lang}"])
        if n > limit:
            over[lang] = n
    return over


def within_tolerance_langs(result: dict, tier: str) -> dict[str, int]:
    """Languages over the ceiling but inside the tolerance: accepted, only logged."""
    strict = over_ceiling_langs(result, tier)
    beyond = over_ceiling_langs(result, tier, WORD_CEILING_TOLERANCE)
    return {lang: n for lang, n in strict.items() if lang not in beyond}


# Exact Latin-script forms the rule requires - taken directly from render.py's
# NEWSPAPER_DISPLAY_NAMES, never re-typed, so this can never drift from the
# canonical list.
APPROVED_NEWSPAPER_NAMES_LATIN = list(NEWSPAPER_DISPLAY_NAMES.values())

# Hebrew-letter renderings of newspaper names that must stay Latin: ONE merged list shared with the daily writer
# (text_checks.NEWSPAPER_NAME_TELLS; PROJECT_LOG 4.82/4.83 for the history, the 2026-11-15 audit for the merge). The old
# names stay as aliases for the code and the dry-run scripts that import them.
TRANSLITERATION_TELLS = NEWSPAPER_NAME_TELLS


def hebrew_newspaper_violations(text: str) -> dict[str, str]:
    return hebrew_newspaper_name_tells(text)


def stray_foreign_script_chars(text: str) -> list[str]:
    """Characters outside Hebrew/Latin/punctuation: the daily writer's whitelist (the old biweekly check was a blacklist of
    Arabic, Cyrillic and Thai only, and missed a Tamil letter that was published)."""
    return foreign_script_chars(text)


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

# Built from the canonical list render.NEWSPAPER_DISPLAY_NAMES (15 names), never typed by hand: the hand-typed list held 11
# names and the four missing ones (Observer, Frankfurter Allgemeine Zeitung, Neue Zürcher Zeitung, The Globe and Mail)
# were the ones written wrongly most often (2026-11-15 audit).
_NEWSPAPER_NAME_LIST = ", ".join(f'"{name}"' for name in NEWSPAPER_DISPLAY_NAMES.values())

BIWEEKLY_STAGE2_SYSTEM_PROMPT = f"""You are a synthesis editor writing ONE section of a biweekly geopolitical trends report. Grouping already happened in an earlier pass: you are given a single recurring real-world story, already identified, together with EVERY one of its own daily write-ups across the two-week period, each one a short comparison already written and published by this same system for its own day, covering how that day's newspaper sources framed the story. You are not going back to the original newspaper articles, the daily write-ups themselves are your only source material.

Your task is fundamentally different from a daily cross-source comparison: it is a cross-TIME comparison of the SAME topic, and it must read as an analyst's brief, not a chronological narrative. Write in exactly this three-part structure, in order:

1. CONCLUSION FIRST (1-2 sentences, always first): state directly what changed in how this story was covered or perceived over the period, the starting framing compared with the latest framing. This is the single most important sentence you write, lead with it, do not build up to it.
2. SELECTED EVIDENCE (2-3 examples only, chosen for how well they illustrate the conclusion, NOT a day-by-day walkthrough): pick the few daily entries that best demonstrate the shift you just stated. Naming 2-3 specific dates/sources as evidence is correct; describing every single daily entry in sequence is not, skip entries that do not add new evidence for your conclusion, even if that means skipping most of the days this topic appeared on.
3. FRAMING DIFFERENCE (at most 1 sentence, only if one is genuinely clear): a single closing sentence on how sources or countries differed in their framing, if and only if there is a clear difference, omit this sentence entirely rather than invent one.

Do NOT narrate "the story began... then on day X... then on day Y... then finally...". Do NOT attempt to mention every daily entry you were given, selecting is part of the task, not a shortcut around it. A reader should get the conclusion in the first sentence, not after working through a timeline.

Date-anchoring (critical): each daily entry you are given is labeled with its own exact calendar date. Some of that daily text may contain relative time language from when it was originally written ("today", "this week", "yesterday", etc.), any such phrase refers ONLY to that entry's own labeled date, never to any other date, and never to "now" or to the end of the two-week period. In your OWN narrative, always use explicit absolute dates (for example "by September 11" or "in the following days, through September 14"), never write "today", "this week", "recently", or any other relative-time phrase yourself, since a biweekly report has no single fixed "today" for the reader.

Reference sources by name only, never by any internal id or page number. Newspaper names: whenever you refer to a source by name, you must use EXACTLY one of these forms, in their original Latin script, never transliterate, translate, abbreviate, or mix scripts, in any language: {_NEWSPAPER_NAME_LIST}. This applies identically inside Hebrew and German text, a Latin-script proper name is never rendered in Hebrew letters or Germanized. For example, a correct Hebrew sentence looks like: "The Daily Telegraph מדווח כי הממשלה הבריטית...", never "הדיילי טלגרף", "טלגרף", or any other transliteration or mangled rendering of the name. The same rule covers ANY other newspaper, magazine or media outlet you mention by name, for example "Financial Times" or "The New York Times" (never "פייננשל טיימס" or "ניו יורק טיימס"): keep its original Latin-script name.

Write natural, fluent prose in each language conveying the same substantive content, not a mechanical translation of one language into another; compose each of comparison_text_he/en/de independently from the same source material.

Hebrew grammar: comparison_text_he must be grammatically correct, standard Hebrew. Pay particular attention to gender agreement between numbers and the nouns they modify (e.g. "שתי כתבות" not "שני כתבות"). The Hebrew word for "drone" is "רחפן" (plural "רחפנים"), never the transliteration "דרון"/"דרונים". Reread each Hebrew sentence for this kind of error before finalizing it.

Students vs. school pupils: the English daily write-ups say "student" for both groups, but Hebrew and German distinguish them. Hebrew "תלמידים" / German "Schüler" are school pupils (high school, lycée); Hebrew "סטודנטים" / German "Studenten" or "Studierende" are university students. Decide from the context in the write-ups (school funding, class sizes, high school, lycée versus campuses, universities, admissions) and never default to "סטודנטים" just because the English word is "student". If the story involves both groups, name both ("תלמידים וסטודנטים"). A movement that is genuinely university-led (for example Serbia's) stays "סטודנטים".

German: topic_label_de and comparison_text_de must read as if written natively in German by a professional journalist, in the same formal-but-readable register (Hochsprache) as this real excerpt of the project's established German house style: "{_GERMAN_STYLE_ANCHOR}". Pay particular attention to German article/adjective/case agreement and noun-number agreement; reread each German sentence for this kind of error before finalizing it.

topic_label_he/en/de are each a short section heading for this story, in their own language, not a translation of one another, and not identical to any single day's own daily label (which only described that one day's angle).

Punctuation in the Hebrew text: do not use a spaced hyphen (" - "), an en dash or an em dash as a separator inside a sentence, in comparison_text_he or in any Hebrew label. Use a comma, a colon, parentheses, or end the sentence and start a new one. Hyphens that belong to the words themselves stay as normal Hebrew usage: a prefix before a number or a Latin name (ב-2028, ה-Guardian), compound names (רוסיה-אוקראינה) and ranges written without spaces (3-4 בספטמבר).

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

Write a brief, genuinely informative overview, 2-3 sentences, in each of Hebrew/English/German, that tells the reader what stood out across the period as a whole, and names any real pattern connecting two or more topics (for example several topics converging on the same region, or a shared theme like escalation/domestic-politics-under-pressure) if one is actually there. Do not simply restate the topic list. If there is no genuine cross-topic pattern, say so plainly rather than inventing one, name the one or two most significant individual topics instead.

Hebrew terminology: the Hebrew word for "drone" is "רחפן" (plural "רחפנים"), never the transliteration "דרון"/"דרונים".

Punctuation in the Hebrew text: do not use a spaced hyphen (" - "), an en dash or an em dash as a separator inside a sentence, in comparison_text_he or in any Hebrew label. Use a comma, a colon, parentheses, or end the sentence and start a new one. Hyphens that belong to the words themselves stay as normal Hebrew usage: a prefix before a number or a Latin name (ב-2028, ה-Guardian), compound names (רוסיה-אוקראינה) and ranges written without spaces (3-4 בספטמבר).

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
    def _call():
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
            return stream.get_final_message()

    response = call_with_retry(f"map {dates[0]}..{dates[-1]}", _call)
    record_usage(response.usage, "biweekly_map")
    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    topics = tool_use.input.get("topics", []) if tool_use else []
    usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    return topics, usage


def map_user_content(dates, rows_by_date):
    rows = []
    for d in dates:
        rows.extend(rows_by_date[d])
    text = format_sections_compact(rows)
    return rows, f"Day-span {dates[0]}..{dates[-1]} ({len(rows)} section(s) total):\n\n{text}"


def run_map(client, window_idx, dates, rows_by_date):
    rows, user_content = map_user_content(dates, rows_by_date)
    valid_ids = {r["id"] for r in rows}

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


REDUCE_ATTEMPTS: list[dict] = []   # one record per reduce call of the current run (raw answer included), cleared by run_reduce


def call_reduce_once(client, user_content, attempt: int = 1):
    def _call():
        with client.messages.stream(
            model=MODEL,
            max_tokens=REDUCE_MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            system=REDUCE_SYSTEM_PROMPT,
            tools=[REDUCE_TOOL],
            tool_choice={"type": "tool", "name": "record_final_topic_groups"},
            messages=[{"role": "user", "content": user_content}],
        ) as stream:
            return stream.get_final_message()

    response = call_with_retry("reduce", _call)
    record_usage(response.usage, "biweekly_reduce")
    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    topics = tool_use.input.get("topics", []) if tool_use else []
    usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    try:   # diagnostics only: a failure here must never fail the call or change what it returns
        REDUCE_ATTEMPTS.append({
            "attempt": attempt, "stop_reason": response.stop_reason, "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"], "tool_use_block": tool_use is not None, "topics_returned": len(topics),
            "tool_input": dict(tool_use.input) if tool_use is not None and isinstance(tool_use.input, dict) else None,
        })
        print(f"    [reduce call attempt {attempt}] stop_reason={response.stop_reason!r}, input_tokens={usage['input_tokens']}, "
              f"output_tokens={usage['output_tokens']}, tool_use block={'yes' if tool_use else 'no'}, topics returned={len(topics)}")
    except Exception as exc:  # noqa: BLE001
        print(f"    [reduce call attempt {attempt}] (diagnostics skipped: {exc!r})")
    if response.stop_reason != "tool_use":
        blocks = ", ".join(
            f"{b.type}:{len(getattr(b, 'thinking', None) or getattr(b, 'text', None) or json.dumps(getattr(b, 'input', ''), ensure_ascii=False))} chars"
            for b in response.content)
        print(f"    [reduce call] non-tool_use stop_reason: {response.stop_reason!r}, "
              f"{response.usage.output_tokens} output tokens of {REDUCE_MAX_TOKENS} allowed "
              f"({'got' if tool_use else 'no'} tool_use block, {len(topics)} topic(s) recovered; blocks: {blocks})")
    warning = reduce_ceiling_warning(response.usage.output_tokens)
    if warning and response.stop_reason != "max_tokens":
        print(f"    *** {warning} ***")
    return topics, usage, response.stop_reason


def reduce_user_content(map_results, sections_by_id):
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
    return len(lines), f"Day-span groups to merge ({len(lines)} total):\n\n" + "\n\n".join(lines)


def save_reduce_rejected(end_date, rejected_attempt: int, used_attempt: int, ratio: float, n_missing: int, n_duplicated: int) -> None:
    """Keeps the reduce answer that was NOT used (the first one when the retry improved, the retry otherwise) with its stop_reason,
    tokens and raw tool input, in data/processed/review_flags/<end>.biweekly_reduce_rejected.json (git-ignored). Diagnostic only:
    never raises and never changes which grouping is used."""
    try:
        record = next((r for r in REDUCE_ATTEMPTS if r["attempt"] == rejected_attempt), None)
        if record is None or not end_date:
            return
        payload = {"period_end": end_date, "rejected_attempt": rejected_attempt, "used_attempt": used_attempt,
                   "problem_ratio": ratio, "missing_count": n_missing, "duplicated_count": n_duplicated,
                   "threshold": BIWEEKLY_GROUPING_RATIO_THRESHOLD, **record}
        REVIEW_FLAGS_DIR.mkdir(parents=True, exist_ok=True)
        (REVIEW_FLAGS_DIR / f"{end_date}.biweekly_reduce_rejected.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"    [reduce] rejected attempt {rejected_attempt} saved to review_flags/{end_date}.biweekly_reduce_rejected.json")
    except Exception as exc:  # noqa: BLE001 - diagnostics must never fail the reduce
        print(f"    [reduce] could not save the rejected attempt: {exc!r}")


def run_reduce(client, map_results, sections_by_id, period=None):
    n_lines, user_content = reduce_user_content(map_results, sections_by_id)

    tokens = count_tokens(client, REDUCE_SYSTEM_PROMPT, user_content)
    print(f"  [reduce] input: {n_lines} day-span topic group(s), {tokens} tokens")

    valid_ids = set(sections_by_id.keys())
    start_date, end_date = period if period else (None, None)

    def log_run(outcome, n_topics, n_missing, n_duplicated, ratio_, retried_, retry_used_, tokens_in, tokens_out, stop):
        record_biweekly_reduce_run(
            start_date=start_date, end_date=end_date, outcome=outcome, input_sections=len(valid_ids),
            input_groups=n_lines, final_topics=n_topics, missing_count=n_missing, duplicated_count=n_duplicated,
            problem_ratio=ratio_, retry_threshold=BIWEEKLY_GROUPING_RATIO_THRESHOLD, retried=int(retried_),
            retry_used=int(retry_used_), input_tokens=tokens_in, output_tokens=tokens_out, stop_reason=stop)

    REDUCE_ATTEMPTS.clear()
    topics, usage, stop_reason = call_reduce_once(client, user_content, attempt=1)
    if stop_reason == "max_tokens":
        log_run("truncated", 0, len(valid_ids), 0, 1.0, False, False, usage["input_tokens"], usage["output_tokens"], stop_reason)
        # A second identical request would be cut at the same place; fail now instead of paying for it.
        raise ReduceFailedError(
            f"reduce output was cut off at the {REDUCE_MAX_TOKENS}-token ceiling ({n_lines} groups, {tokens} input "
            f"tokens) - raise REDUCE_MAX_TOKENS or split the reduce; nothing was checkpointed or written")
    missing, duplicated, ratio = compute_stage1_problem_ratio(topics, valid_ids, key="section_ids")
    usages = [usage]
    retries = 0
    retry_used = False
    final_stop = stop_reason

    if ratio > BIWEEKLY_GROUPING_RATIO_THRESHOLD:
        retries += 1
        print(f"  [reduce] {len(missing)} missing + {len(duplicated)} duplicated ({ratio:.1%}) exceeds "
              f"{BIWEEKLY_GROUPING_RATIO_THRESHOLD:.0%} - retrying once.")
        first_ratio, first_missing, first_duplicated = ratio, len(missing), len(duplicated)
        retry_topics, retry_usage, retry_stop = call_reduce_once(client, user_content, attempt=2)
        usages.append(retry_usage)
        retry_missing, retry_duplicated, retry_ratio = compute_stage1_problem_ratio(retry_topics, valid_ids, key="section_ids")
        if retry_stop != "max_tokens" and retry_ratio < ratio:
            topics, missing, duplicated, ratio = retry_topics, retry_missing, retry_duplicated, retry_ratio
            retry_used, final_stop = True, retry_stop
            print(f"    retry improved ({ratio:.1%}) - using the retry result.")
            save_reduce_rejected(end_date, 1, 2, first_ratio, first_missing, first_duplicated)
        else:
            print(f"    retry did not improve - keeping the original grouping.")
            save_reduce_rejected(end_date, 2, 1, retry_ratio, len(retry_missing), len(retry_duplicated))

    total_usage = {
        "input_tokens": sum(u["input_tokens"] for u in usages),
        "output_tokens": sum(u["output_tokens"] for u in usages),
    }
    print(f"  [reduce] -> {len(topics)} final topic(s), final: {len(missing)} missing, {len(duplicated)} duplicated")
    log_run("ok" if topics else "empty", len(topics), len(missing), len(duplicated), ratio, retries > 0, retry_used,
            total_usage["input_tokens"], total_usage["output_tokens"], final_stop)
    if not topics:
        raise ReduceFailedError(f"reduce returned no topics for {n_lines} groups - nothing was checkpointed or written")
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
        _, window_content = map_user_content(window_dates, rows_by_date)
        ck_path = _checkpoint_path(start, end, f"map{i}", _content_key(MODEL, MAP_SYSTEM_PROMPT, MAP_TOOL, window_content))
        ck = load_checkpoint(ck_path)
        if ck is not None:
            topics = ck["topics"]
            print(f"  [map window {i}] {window_dates[0]}..{window_dates[-1]}: reusing checkpoint ({len(topics)} topic(s)) - no API call")
        else:
            topics, usage, retries = run_map(client, i, window_dates, rows_by_date)
            save_checkpoint(ck_path, topics, usage, retries)
        map_results.append((f"W{i}({window_dates[0]}..{window_dates[-1]})", topics))

    _, reduce_content = reduce_user_content(map_results, sections_by_id)
    rk_path = _checkpoint_path(start, end, "reduce", _content_key(MODEL, REDUCE_SYSTEM_PROMPT, REDUCE_TOOL, reduce_content))
    rk = load_checkpoint(rk_path)
    if rk is not None:
        final_topics = rk["topics"]
        print(f"  reduce: reusing checkpoint ({len(final_topics)} final topic(s)) - no API call")
    else:
        print("  running reduce...")
        final_topics, usage, retries = run_reduce(client, map_results, sections_by_id, period=(start, end))
        save_checkpoint(rk_path, final_topics, usage, retries)

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
    response = call_with_retry(f"topic {topic['topic_label_en'][:40]}", lambda: client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=[{"type": "text", "text": BIWEEKLY_STAGE2_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        tools=[BIWEEKLY_COMPARE_TOOL],
        tool_choice={"type": "tool", "name": "record_biweekly_topic"},
        messages=[{"role": "user", "content": user_content}],
    ))
    record_usage(response.usage, "biweekly_topic")
    tool_use = next(b for b in response.content if b.type == "tool_use")
    result = dict(tool_use.input)
    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
    }
    return result, usage


def _rules_reminder(tier: str) -> str:
    """Appended to EVERY retry feedback: a retry that names only the rule that failed let the rewrite break another one
    (12.11: attempt 1 over the word ceiling, attempt 2 a newspaper name in Hebrew letters, topic dropped)."""
    ceiling = WORD_CEILINGS[tier]
    return (
        " FULL REMINDER OF ALL RULES (every rule applies to the rewrite, not only the one that failed): "
        "(1) newspaper names: only these exact Latin-script forms, verbatim inside Hebrew and German text, never in Hebrew letters or "
        f"transliterated, also when the newspaper is itself the subject of the story: {_NEWSPAPER_NAME_LIST}; any other outlet keeps its "
        "original Latin name too; "
        f"(2) length: comparison_text_he, comparison_text_en and comparison_text_de must each be at most {ceiling} words, counted "
        f"separately per language; aim for about {int(ceiling * 0.9)} words so you land under the limit; "
        "(3) characters: Hebrew text only in Hebrew letters, other text in Latin letters; never a letter of any other writing system; "
        "never a Latin letter inside a Hebrew word or a Hebrew letter inside a Latin word (a Hebrew prefix goes before a Latin name with "
        "a hyphen, for example ב-The Guardian); "
        "(4) fields: each field holds only its own plain text in its own language, with no markup, tags or field names; "
        "(5) punctuation: no spaced hyphen, en dash or em dash as a separator in the Hebrew text; "
        "(6) structure: conclusion first, 2-3 selected examples, at most one framing-difference sentence; absolute dates only; "
        "Hebrew gender agreement; native German."
    )


# --- 3. rejected text goes to review_flags --------------------------------------------------------------------------------------
REVIEW_FLAGS_DIR = PROJECT_ROOT / "data" / "processed" / "review_flags"
BIWEEKLY_REJECTED: list[dict] = []   # every attempt whose text was thrown away, with the reasons (this process)


def _record_rejected(topic: dict, attempt: int, outcome: str, reasons: list[str], result: dict | None) -> None:
    try:
        entry = {"topic": topic.get("topic_label_en", "?"), "attempt": attempt, "outcome": outcome, "reasons": reasons,
                 "text": {f: (result or {}).get(f) for f in _BIWEEKLY_FIELDS} if result else None}
        with _LOG_ONLY_LOCK:
            BIWEEKLY_REJECTED.append(entry)
    except Exception:  # noqa: BLE001 - recording must never fail a topic
        pass


def write_rejected_report(end: str) -> str:
    """Saves the rejected attempts to data/processed/review_flags/<end>.biweekly_rejected.json and returns the one summary line
    (attempts thrown away, topics dropped, reasons). Never raises; the summary is printed even when nothing was rejected."""
    with _LOG_ONLY_LOCK:
        entries = list(BIWEEKLY_REJECTED)
    dropped = [e for e in entries if e["outcome"] == "dropped"]
    reasons = sorted({r.split(":")[0] for e in dropped for r in e["reasons"]})
    line = (f"Biweekly rejected text: {len(entries)} attempt(s) thrown away, {len(dropped)} topic(s) dropped"
            + (f" (reasons: {', '.join(reasons)})" if reasons else "")
            + (f"; saved to review_flags/{end}.biweekly_rejected.json" if entries else ""))
    try:
        if entries:
            REVIEW_FLAGS_DIR.mkdir(parents=True, exist_ok=True)
            (REVIEW_FLAGS_DIR / f"{end}.biweekly_rejected.json").write_text(
                json.dumps({"period_end": end, "attempts": entries}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    except OSError as exc:
        line += f" (could not write the file: {exc})"
    return line


# --- 4. checkpoint of finished topics ---------------------------------------------------------------------------------------------
def _topic_checkpoint_path(period: tuple[str, str], topic: dict, days: list[dict]) -> Path:
    key = _content_key(MODEL, BIWEEKLY_STAGE2_SYSTEM_PROMPT, BIWEEKLY_COMPARE_TOOL, topic["topic_label_en"],
                       topic["n_distinct_days"], topic["n_sources"], DEPTH_INSTRUCTIONS[depth_tier(topic["n_distinct_days"])],
                       format_topic_days(days))
    return _checkpoint_path(period[0], period[1], "topic", key)


def write_topic_checkpointed(client, topic: dict, days: list[dict], period: tuple[str, str] | None):
    """write_biweekly_topic_with_retry with a per-topic checkpoint: a finished topic is saved to disk, and a later run of the same
    period (after a crash, a failed DB write or a manual re-run) re-uses it instead of paying for it again. A dropped topic is never
    checkpointed (a re-run tries it again). The key covers the model, the prompt, the tool schema, the tier text and the topic's
    own input, so any change to them makes the checkpoint invisible. Same return value as the function it wraps."""
    if period is None:
        return write_biweekly_topic_with_retry(client, topic, days)
    path = _topic_checkpoint_path(period, topic, days)
    ck = load_checkpoint(path)
    if ck:
        print(f"  topic '{topic['topic_label_en']}': reusing checkpoint - no API call")
        return ck["topics"][0], {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}, {}
    result, usage, over = write_biweekly_topic_with_retry(client, topic, days)
    if result is not None:
        save_checkpoint(path, [result], usage, 0)
    return result, usage, over


_BIWEEKLY_FIELDS = ("topic_label_he", "topic_label_en", "topic_label_de",
                    "comparison_text_he", "comparison_text_en", "comparison_text_de")
# Clean-up that never needs a retry (counted in the log): a Hebrew prefix glued to a Latin name gets its hyphen, and the
# Latin name forms that are deliberately not checked (a missing "The", FAZ/NZZ/SZ) are only counted (decided 2026-11-15).
BIWEEKLY_LOG_ONLY: dict = {"prefix_hyphen": 0, "missing_the": 0, "abbreviations": 0}
BIWEEKLY_PREFIX_FIXES: list[str] = []   # one "field: before -> after" line per hyphen repair, printed with the text-fix summary
_LOG_ONLY_LOCK = threading.Lock()


def _biweekly_problems(result: dict) -> dict[str, dict]:
    """Retry-worthy defects (text_checks.writer_problems) over every field the writer produced: characters outside
    Hebrew/Latin, Hebrew and Latin letters fused in a word, markup or field names in the text, a Hebrew field that is
    mostly not Hebrew. The newspaper-name tells, the word ceiling and the placeholder check are checked separately."""
    return writer_problems({f: result.get(f, "") for f in _BIWEEKLY_FIELDS}, hebrew_fields=("comparison_text_he",))


def _record_prefix_fix_snippets(label: str, original: str) -> None:
    """Diagnostics only: remembers each before/after snippet of a hyphen repair. Never raises."""
    try:
        pairs = attached_prefix_repairs(original)
        with _LOG_ONLY_LOCK:
            for before, after in pairs:
                BIWEEKLY_PREFIX_FIXES.append(f"{label}: \"{before}\" -> \"{after}\"")
    except Exception:  # noqa: BLE001
        pass


def print_prefix_fixes(end_date: str, max_lines: int = 10) -> None:
    """First `max_lines` snippets in the log, all of them in review_flags/<end>.biweekly_prefix_fixes.json (git-ignored). Never raises."""
    try:
        with _LOG_ONLY_LOCK:
            fixes = list(BIWEEKLY_PREFIX_FIXES)
        for line in fixes[:max_lines]:
            print(f"  prefix hyphen fix {line}")
        if len(fixes) > max_lines:
            print(f"  prefix hyphen fix: {len(fixes) - max_lines} more in review_flags/{end_date}.biweekly_prefix_fixes.json")
        if fixes:
            REVIEW_FLAGS_DIR.mkdir(parents=True, exist_ok=True)
            (REVIEW_FLAGS_DIR / f"{end_date}.biweekly_prefix_fixes.json").write_text(
                json.dumps({"period_end": end_date, "fixes": fixes}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - diagnostics must never fail the run
        print(f"  (prefix hyphen snippets not saved: {exc!r})")


def _finish_biweekly_result(result: dict) -> dict:
    """Retry-free clean-up of an accepted result: the hyphen after a Hebrew prefix glued to a Latin name, plus the log-only
    name-form counts. Never raises, never rejects."""
    try:
        counts = {"prefix_hyphen": 0, "missing_the": 0, "abbreviations": 0}
        for field in ("topic_label_he", "comparison_text_he"):
            original = result.get(field, "")
            fixed, n = fix_attached_prefixes(original)
            if n:
                result[field] = fixed
                counts["prefix_hyphen"] += n
                _record_prefix_fix_snippets(f"[{result.get('topic_label_en', '?')}] {field}", original)
        for lang in ("he", "en", "de"):
            forms = latin_name_form_counts(result.get(f"comparison_text_{lang}", ""))
            counts["missing_the"] += forms["missing_the"]
            counts["abbreviations"] += forms["abbreviations"]
        with _LOG_ONLY_LOCK:
            for k, v in counts.items():
                BIWEEKLY_LOG_ONLY[k] += v
    except Exception:  # noqa: BLE001 - clean-up and logging must never fail a topic
        pass
    return result


def write_biweekly_topic_with_retry(client, topic: dict, days: list[dict]):
    """Four guards feed the same single retry (attempt 0 only):
    _looks_suspicious (placeholder/garbage output -> drop on repeat failure),
    over_ceiling_langs (word-count over tier ceiling -> keep-and-flag on
    repeat failure), hebrew_newspaper_name_tells (newspaper name in Hebrew
    letters -> drop on repeat failure), and the shared text checks of
    text_checks.writer_problems (foreign-script letters by the daily whitelist in
    all three languages, Hebrew and Latin fused in one word, markup or field names
    in the text, a Hebrew field that is mostly not Hebrew -> drop on repeat
    failure). See PROJECT_LOG 4.82/4.83 for why the first three were added."""
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
        over = over_ceiling_langs(result, tier, WORD_CEILING_TOLERANCE)
        last_over = over
        tolerated = within_tolerance_langs(result, tier)
        if tolerated:
            print(f"  topic '{topic['topic_label_en']}' attempt {attempt + 1}: "
                  + ", ".join(f"{lang}={n}w" for lang, n in tolerated.items())
                  + f" over the {WORD_CEILINGS[tier]}-word ceiling but within the {int(WORD_CEILING_TOLERANCE * 100)}% tolerance - accepted, no retry.")

        he_fields = result["comparison_text_he"] + " " + result["topic_label_he"]
        newspaper_hits = hebrew_newspaper_name_tells(he_fields)
        problems = _biweekly_problems(result)

        if (suspicious_langs or over or newspaper_hits or problems) and attempt == 0:
            reasons = []
            if suspicious_langs:
                reasons.append(f"suspicious output in: {', '.join(suspicious_langs)}")
            if over:
                reasons.append("over the " + f"{WORD_CEILINGS[tier]}-word ceiling: "
                                + ", ".join(f"{lang}={n}w" for lang, n in over.items()))
            if newspaper_hits:
                reasons.append(f"Hebrew newspaper-name violation: {list(newspaper_hits.keys())}")
            if problems:
                reasons.append(f"text problems ({problem_kind(problems)}): "
                               + "; ".join(f"{kind}={list(by.keys())}" for kind, by in problems.items()))
            print(f"  topic '{topic['topic_label_en']}' attempt {attempt + 1}: {'; '.join(reasons)} - retrying once.")
            feedback_parts = []
            if over:
                feedback_parts.append(
                    "Your previous attempt exceeded the word ceiling for this tier: "
                    + ", ".join(f"{lang} was {n} words (limit {WORD_CEILINGS[tier]})" for lang, n in over.items())
                    + ". Cut it down to fit within the limit in each of those languages, keeping the "
                    "conclusion-first structure (do not pad the other languages to match - each has its own limit)."
                )
            if newspaper_hits:
                corrections = "; ".join(f'"{tell}" should have been "{name}"' for tell, name in newspaper_hits.items())
                feedback_parts.append(
                    "Your previous attempt violated the newspaper-name rule in comparison_text_he/"
                    "topic_label_he: it rendered a newspaper name in Hebrew letters instead of keeping "
                    "it in its exact Latin-script form. "
                    + (f"Specifically: {corrections}. " if corrections else "")
                    + "Rewrite the Hebrew text so every newspaper reference uses its exact Latin-script "
                    "name verbatim (e.g. \"Süddeutsche Zeitung\", \"The Wall Street Journal\") embedded "
                    "directly inside the Hebrew sentence, never transliterated, never in Hebrew letters."
                )
            if problems:
                feedback_parts.append("Your previous attempt had a text defect: " + problems_feedback(problems) + ".")
            feedback = " ".join(feedback_parts) + _rules_reminder(tier)
            _record_rejected(topic, attempt + 1, "retried", reasons, result)
            continue

        if suspicious_langs:
            print(f"  topic '{topic['topic_label_en']}' still suspicious after retry - dropping.")
            _record_rejected(topic, attempt + 1, "dropped", [f"suspicious: {', '.join(suspicious_langs)}"], result)
            return None, usage_totals, {}
        if newspaper_hits:
            print(f"  topic '{topic['topic_label_en']}' still has a newspaper-name violation after retry - dropping.")
            _record_rejected(topic, attempt + 1, "dropped", [f"newspaper_names: {', '.join(newspaper_hits)}"], result)
            return None, usage_totals, {}
        if problems:
            print(f"  topic '{topic['topic_label_en']}' still has a text defect after retry ({problem_kind(problems)}) - dropping.")
            _record_rejected(topic, attempt + 1, "dropped", [f"{problem_kind(problems)}: " + "; ".join(f"{k}={list(v)}" for k, v in problems.items())], result)
            return None, usage_totals, {}
        if over:
            print(f"  topic '{topic['topic_label_en']}' still over ceiling after retry "
                  f"({', '.join(f'{lang}={n}w' for lang, n in over.items())}) - keeping anyway, flagged.")
        return _finish_biweekly_result(result), usage_totals, over
    return None, usage_totals, last_over


def write_overview(client, topics: list[dict], feedback: str = "") -> tuple[dict, dict]:
    lines = [f"- {t['topic_label_en']} ({t['n_distinct_days']}d, {t['n_sources']} src)" for t in topics]
    user_content = "Topics in this edition, by source-breadth:\n\n" + "\n".join(lines)
    if feedback:
        user_content += "\n\n" + feedback
    response = call_with_retry("overview", lambda: client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=OVERVIEW_SYSTEM_PROMPT,
        tools=[OVERVIEW_TOOL],
        tool_choice={"type": "tool", "name": "record_overview"},
        messages=[{"role": "user", "content": user_content}],
    ))
    record_usage(response.usage, "biweekly_overview")
    tool_use = next(b for b in response.content if b.type == "tool_use")
    result = dict(tool_use.input)
    usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    return result, usage


def _overview_problems(overview: dict) -> tuple[dict, dict, list[str]]:
    """(text problems by kind, newspaper-name tells, suspicious languages) of an overview, by the same checks as a topic."""
    fields = {f"overview_{lang}": overview.get(f"overview_{lang}", "") for lang in ("he", "en", "de")}
    problems = writer_problems(fields, hebrew_fields=("overview_he",))
    tells = hebrew_newspaper_name_tells(fields["overview_he"])
    suspicious = [lang for lang in ("he", "en", "de") if _looks_suspicious(fields[f"overview_{lang}"])]
    return problems, tells, suspicious


def write_overview_checked(client, topics: list[dict]) -> tuple[dict, dict]:
    """The overview used to be unchecked. Same guards as a topic (shared text checks, newspaper names in Hebrew letters,
    placeholder output), one retry with feedback; a repeat failure keeps the overview (a report without one is worse) and
    says so loudly in the log. The prefix hyphen is repaired deterministically."""
    overview, usage = write_overview(client, topics)
    problems, tells, suspicious = _overview_problems(overview)
    if problems or tells or suspicious:
        parts = []
        if problems:
            parts.append("Your previous attempt had a text defect: " + problems_feedback(problems) + ".")
        if tells:
            parts.append("Your previous attempt wrote newspaper names in Hebrew letters: "
                         + "; ".join(f'"{t}" should have been "{n}"' for t, n in tells.items())
                         + ". Use the exact Latin-script names, never transliterated.")
        if suspicious:
            parts.append(f"Your previous attempt produced empty or placeholder text in: {', '.join(suspicious)}.")
        print(f"  overview needs a rewrite ({', '.join(list(problems) + (['newspaper_names'] if tells else []) + (['suspicious'] if suspicious else []))}) - retrying once.")
        try:
            retry, usage = write_overview(client, topics, feedback=" ".join(parts))
            overview = retry
        except Exception as exc:
            print(f"  overview retry failed ({exc}) - keeping the first overview.")
        problems, tells, suspicious = _overview_problems(overview)
        if problems or tells or suspicious:
            print("  *** WARNING: the overview still has a defect after the retry "
                  f"({', '.join(list(problems) + (['newspaper_names'] if tells else []) + (['suspicious'] if suspicious else []))}) - kept, needs a human look.")
    original_overview = overview.get("overview_he", "")
    fixed, n = fix_attached_prefixes(original_overview)
    if n:
        overview["overview_he"] = fixed
        with _LOG_ONLY_LOCK:
            BIWEEKLY_LOG_ONLY["prefix_hyphen"] += n
        _record_prefix_fix_snippets("[overview] overview_he", original_overview)
    return overview, usage


def run_stage2(client, conn, topics: list[dict], period: tuple[str, str] | None = None) -> tuple[dict, list[dict]]:
    for t in topics:
        t["_days"] = load_topic_days(conn, t)

    tier_counts = {"deep": 0, "developed": 0, "concise": 0}
    for t in topics:
        tier_counts[depth_tier(t["n_distinct_days"])] += 1
    print(f"Stage 2: writing {len(topics)} topic(s). Depth tiers: {tier_counts}")

    results: dict[str, dict] = {}
    failed = []
    for key in BIWEEKLY_LOG_ONLY:
        BIWEEKLY_LOG_ONLY[key] = 0
    BIWEEKLY_PREFIX_FIXES.clear()
    BIWEEKLY_REJECTED.clear()

    first = topics[0]
    print(f"  cache-warming with: {first['topic_label_en']}")
    result, usage, over = write_topic_checkpointed(client, first, first["_days"], period)
    if result is None:
        failed.append(first["topic_label_en"])
    else:
        results[first["topic_label_en"]] = result

    remaining = topics[1:]
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        future_to_topic = {
            executor.submit(write_topic_checkpointed, client, t, t["_days"], period): t for t in remaining
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
    overview, _ = write_overview_checked(client, kept_topics)
    print("Biweekly text fixes (no retry): prefix_hyphen=%d | name forms (counted, never checked): missing_the=%d abbreviations=%d"
          % (BIWEEKLY_LOG_ONLY["prefix_hyphen"], BIWEEKLY_LOG_ONLY["missing_the"], BIWEEKLY_LOG_ONLY["abbreviations"]))
    print_prefix_fixes(period[1] if period else date.today().isoformat())
    print(write_rejected_report(period[1] if period else date.today().isoformat()))
    return overview, kept_topics


def write_period_to_db(conn, start: str, end: str, overview: dict, topics: list[dict], force: bool) -> int:
    """All-or-nothing: every row of the period (and, under --force, the delete
    of the one it replaces) goes into a single transaction. Committing per row
    would let a crash mid-write leave a period row with only some of its
    topics - and since every later run skips a period whose row already
    exists, that partial report would stay published with nothing flagging it."""
    if biweekly_period_exists(conn, end) and not force:
        raise SystemExit(f"Period ending {end} already exists - pass --force to overwrite.")

    try:
        if force:
            delete_biweekly_period(conn, end, commit=False)
        period_id = insert_biweekly_period(
            conn, start, end,
            overview["overview_he"], overview["overview_en"], overview["overview_de"],
            datetime.now(timezone.utc).isoformat(),
            commit=False,
        )
        for sort_order, t in enumerate(topics):
            r = t["result"]
            topic_id = insert_biweekly_topic(
                conn, period_id,
                r["topic_label_he"], r["topic_label_en"], r["topic_label_de"],
                r["comparison_text_he"], r["comparison_text_en"], r["comparison_text_de"],
                t["n_distinct_days"], t["n_sources"], sort_order,
                commit=False,
            )
            # dict.fromkeys() de-dup - see scripts/migrate_biweekly_dryrun_to_db.py
            # for why a section id can legitimately repeat within one topic's list.
            for section_id in dict.fromkeys(t["section_ids"]):
                link_biweekly_topic_section(conn, topic_id, section_id, commit=False)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return period_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Biweekly narrative-trends report (map-reduce + narrative writing).")
    parser.add_argument("--start", default=None, help="Period start, YYYY-MM-DD. Omit with --end to auto-detect today's closing period.")
    parser.add_argument("--end", default=None, help="Period end, YYYY-MM-DD.")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing period for this end date.")
    parser.add_argument(
        "--allow-missing-days", action="store_true",
        help="Synthesize even though some days in the period have no published daily report "
             "(a known, permanent gap in the archive). Without it the run refuses and lists the "
             "missing dates. Separate from --force on purpose: overwriting a period and accepting "
             "an incomplete one are different decisions.",
    )
    parser.add_argument(
        "--stage1-only", action="store_true",
        help="Run only the grouping stage (map + reduce), print its token usage/cost, and stop before any "
             "narrative writing. Map/reduce results are checkpointed, so a following full run re-uses them.",
    )
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

    # Before any API call and long before anything is written: a period row
    # built from fewer days than its label says would be indistinguishable,
    # to every later run, from a finished one.
    try:
        start_d, end_d = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError as e:
        parser.error(f"--start/--end must be YYYY-MM-DD ({e})")
    if start_d > end_d:
        parser.error(f"--start ({start}) is after --end ({end}).")
    missing = missing_published_days(
        start_d, end_d, get_report_dates_in_range(conn, start, end), PROJECT_ROOT / "docs"
    )
    if missing:
        total_days = (end_d - start_d).days + 1
        listing = ", ".join(missing)
        if not args.allow_missing_days:
            print(
                f"REFUSING to synthesize {start}..{end}: {len(missing)} of {total_days} day(s) have no "
                f"published daily report:\n  {listing}\n"
                f"Nothing was written. Publish those daily reports first, or - only if these days are a "
                f"known, permanent gap - re-run with --allow-missing-days.",
                file=sys.stderr,
            )
            conn.close()
            return 2
        print(f"WARNING (--allow-missing-days): proceeding without {len(missing)} of {total_days} day(s): {listing}")

    client = anthropic.Anthropic()

    try:
        stage1_topics = run_stage1(client, conn, start, end)
    except ReduceFailedError as exc:
        print(f"REDUCE FAILED for {start}..{end}: {exc}", file=sys.stderr)
        conn.close()
        return EXIT_REDUCE_FAILED
    if not stage1_topics:
        print("No sections found for this period - nothing to synthesize.", file=sys.stderr)
        conn.close()
        return 0 if args.stage1_only else EXIT_NO_TOPICS

    print(usage_summary("stage 1"))
    if args.stage1_only:
        print(f"--stage1-only: stopping after stage 1 ({len(stage1_topics)} grouped topic(s)); nothing written to the DB.")
        conn.close()
        return 0

    topics = load_topics_for_stage2(conn, stage1_topics)
    print(f"{len(topics)} topic(s) cleared the >={MIN_DISTINCT_DAYS}-day inclusion threshold.")
    if not topics:
        print("No topic cleared the inclusion threshold - no report for this period.", file=sys.stderr)
        conn.close()
        return EXIT_NO_TOPICS

    overview, kept_topics = run_stage2(client, conn, topics, period=(start, end))

    period_id = write_period_to_db(conn, start, end, overview, kept_topics, args.force)
    print(f"Wrote biweekly period id={period_id} ({start}..{end}), {len(kept_topics)} topic(s), to tracker.db.")
    print(usage_summary("full run"))
    removed = clear_checkpoints(start, end)
    if removed:
        print(f"Removed {removed} checkpoint file(s) for {start}..{end}.")

    conn.close()
    return 0


if __name__ == "__main__":
    started = usage_marker()
    try:
        code = main()
    finally:
        print_usage_summary("biweekly", started, "biweekly_")
    sys.exit(code)
