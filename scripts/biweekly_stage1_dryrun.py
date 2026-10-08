"""One-off dry-run experiment (NOT a pipeline stage, NOT wired into daily_autorun.py
or any production script) testing whether cross-day topic clustering for the planned
biweekly narrative-trends report needs a map-reduce split, per the diagnostic finding
that a 14-day window (P2, 2026-09-03..2026-09-16, 207,191 tokens after excluding
additional_coverage fallback sections) is 2.78x the input size of the single largest
day daily Stage 1 has ever handled (2026-10-02, 499 articles, 74,557 tokens).

Map: split P2 into token-budgeted sub-windows (~45K tokens each, using the SAME
compact-item philosophy as synthesize.py's format_articles_compact() - label + a
short gist, not full prose), and run the same kind of grouping call synthesize.py's
Stage 1 already uses (same tool-schema shape, same model/params), just with
"item" = one day's report_section instead of one article.

Reduce: a second, much smaller call that only sees each sub-window's already-
compact grouping output (topic labels + contributing section ids/dates) and merges
recurring real-world story threads across sub-windows into the final cross-P2 list.

Writes nothing to the DB and publishes nothing - this is read-only against
tracker.db plus two real (paid) Claude API call batches (map + reduce), printed to
stdout and saved to a local JSON file in scripts/output/ for inspection.
"""
import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import anthropic
from dotenv import load_dotenv

from src.common.db import get_connection
from src.reporting.synthesize import compute_stage1_problem_ratio

load_dotenv()

WINDOW_START = "2026-09-03"
WINDOW_END = "2026-09-16"
TARGET_TOKENS_PER_MAP_WINDOW = 45000
MODEL = "claude-sonnet-5"
GIST_CHARS = 280  # how much of comparison_text_en each compact item carries

# Deliberately SEPARATE from synthesize.py's GROUPING_RATIO_THRESHOLD (20%) -
# that one is calibrated for daily Stage 1's near-total-failure days (e.g.
# 2026-09-18's ~100%-unassigned first attempt) and does NOT touch this
# constant. This one is calibrated from THIS script's own measured ratios
# (2026-10-07 diagnostic): map window 1 = 39/339 = 11.50%, map window 2 =
# 13/345 = 3.77%, and reduce's own output (retrospectively computed from the
# un-retried run) = 66/684 = 9.65% - including the two concrete cases (daily
# section_ids 1337 and 1706) where reduce itself assigned the same id to two
# different final topics, independent of anything inherited from daily. 8%
# sits strictly between the one clean-looking window (3.77%) and the two
# problem cases (9.65%, 11.50%), so it retries exactly the cases that showed
# the problem without forcing a pointless retry on the window that didn't.
BIWEEKLY_GROUPING_RATIO_THRESHOLD = 0.08

OUTPUT_DIR = Path(__file__).resolve().parent / "output"

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

REDUCE_SYSTEM_PROMPT = """You are finishing the first pass of a biweekly narrative trends report for a geopolitical news tracker. Several short day-spans within a two-week period were already each independently grouped into real-world story threads (by an earlier pass over that day-span alone). You will be given all of those day-span groups together - each with a label, the ids/dates it covers, and a short gist drawn from one of its contributing entries.

Your task: merge groups from DIFFERENT day-spans that are clearly the same real-world story continuing across the full two-week period, even if their labels are worded differently (they were written independently, by day-span, without seeing each other). Where a story only appears in one day-span, keep it as its own final topic unchanged - do not force unrelated items together. Do NOT write any narrative prose - a later pass handles that, once the final grouping is settled.

For each FINAL merged topic, call record_final_topic_groups with:
- topic_label_en: a short label for the real-world story, in English.
- section_ids: the union of every section id from every day-span group you merged into this topic.

Every section id you were given (across all day-span groups) must appear in exactly one final topic's section_ids."""

REDUCE_TOOL = {
    "name": "record_final_topic_groups",
    "description": "Merge day-span topic groups into the final cross-period list of real-world story threads.",
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


def gist_of(text: str) -> str:
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= GIST_CHARS:
        return text
    cut = text[:GIST_CHARS]
    last_period = cut.rfind(". ")
    if last_period > GIST_CHARS * 0.5:
        return cut[: last_period + 1]
    return cut + "…"


def format_sections_compact(rows) -> str:
    blocks = []
    for r in rows:
        blocks.append(
            f"id={r['id']} | date={r['report_date']} | topic: {r['topic_label_en']}\n"
            f"  gist: {gist_of(r['comparison_text_en'])}"
        )
    return "\n\n".join(blocks)


def count_tokens(client, system, user_content) -> int:
    result = client.messages.count_tokens(
        model=MODEL,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )
    return result.input_tokens


def build_windows(client, rows_by_date):
    """Greedy day-by-day accumulation against TARGET_TOKENS_PER_MAP_WINDOW,
    measured on the actual compact representation that will be sent (not full
    comparison_text), via real count_tokens calls - no chars/token guessing."""
    dates = sorted(rows_by_date.keys())
    windows = []
    current_dates: list[str] = []

    def current_rows():
        out = []
        for d in current_dates:
            out.extend(rows_by_date[d])
        return out

    for d in dates:
        trial_dates = current_dates + [d]
        trial_rows = []
        for dd in trial_dates:
            trial_rows.extend(rows_by_date[dd])
        trial_text = format_sections_compact(trial_rows)
        trial_tokens = count_tokens(client, MAP_SYSTEM_PROMPT, trial_text)
        if current_dates and trial_tokens > TARGET_TOKENS_PER_MAP_WINDOW:
            # Close out the current window before adding this day.
            windows.append(list(current_dates))
            current_dates = [d]
        else:
            current_dates = trial_dates
    if current_dates:
        windows.append(list(current_dates))
    return windows


def call_map_once(client, dates, rows, user_content):
    # Streaming (not .create()) per house convention for any high-max_tokens call -
    # the Anthropic SDK itself refuses a non-streaming call once max_tokens is high
    # enough that the request could plausibly exceed its 10-minute client-side
    # timeout (hit in practice on the reduce call, see call_reduce_once below).
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
    """Same missing+duplicate detection as daily Stage 1 (compute_stage1_problem_ratio,
    reused directly from synthesize.py, not re-implemented) but gated by this
    script's OWN BIWEEKLY_GROUPING_RATIO_THRESHOLD, not synthesize.py's 20% -
    this is exactly the check that was missing when this script first ran and
    found 13 missing + 53
    duplicated section ids out of 684 in a single-shot, no-retry attempt."""
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
        print(
            f"  [map window {window_idx}] {dates[0]}..{dates[-1]}: {len(missing)} missing + "
            f"{len(duplicated)} duplicated ({ratio:.1%}) exceeds {BIWEEKLY_GROUPING_RATIO_THRESHOLD:.0%} - retrying once."
        )
        retry_topics, retry_usage = call_map_once(client, dates, rows, user_content)
        usages.append(retry_usage)
        retry_missing, retry_duplicated, retry_ratio = compute_stage1_problem_ratio(
            retry_topics, valid_ids, key="section_ids"
        )
        if retry_ratio < ratio:
            print(f"    retry improved ({ratio:.1%} -> {retry_ratio:.1%}) - using the retry result.")
            topics, missing, duplicated, ratio = retry_topics, retry_missing, retry_duplicated, retry_ratio
        else:
            print(f"    retry did not improve ({ratio:.1%} -> {retry_ratio:.1%}) - keeping the original grouping.")
        if ratio > BIWEEKLY_GROUPING_RATIO_THRESHOLD:
            print(
                f"    *** QUALITY WARNING ***: still {ratio:.1%} after retry "
                f"({len(missing)} missing, {len(duplicated)} duplicated) - accepting as-is."
            )

    total_usage = {
        "input_tokens": sum(u["input_tokens"] for u in usages),
        "output_tokens": sum(u["output_tokens"] for u in usages),
    }
    print(
        f"  [map window {window_idx}] {dates[0]}..{dates[-1]} ({len(rows)} sections, "
        f"{total_usage['input_tokens']} input tok across {len(usages)} call(s)) -> {len(topics)} topic(s), "
        f"final: {len(missing)} missing, {len(duplicated)} duplicated"
    )
    return topics, total_usage, retries


def call_reduce_once(client, user_content):
    # Streaming (not .create()) - at max_tokens=24000 the Anthropic SDK itself
    # raises "Streaming is required for operations that may take longer than
    # 10 minutes" on a plain .create() call. .get_final_message() collects the
    # full streamed response so the rest of this function is unchanged.
    with client.messages.stream(
        model=MODEL,
        # Bumped from 16000 to 24000 (2026-10-08) after a real P3 failure: with
        # 472 day-span topic groups as input (vs P2's ~453-476, similar
        # magnitude but apparently right at the edge), the response hit
        # max_tokens before completing a tool_use block at all on BOTH the
        # original attempt and the (blind) retry - stop_reason="max_tokens",
        # zero topics recovered either time. The existing retry only checks
        # missing/duplicated counts, not stop_reason, so a token-budget
        # failure isn't something a blind retry of the identical prompt can
        # fix - more headroom is the actual fix.
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
    """map_results: list of (window_label, topics) where each topic has
    topic_label_en + section_ids. Builds one compact entry per day-span topic,
    carrying a gist from its FIRST contributing section for semantic signal.

    Same BIWEEKLY_GROUPING_RATIO_THRESHOLD retry policy as run_map() above -
    added 2026-10-07 after a section_id-level diagnostic found reduce's own
    output (not inherited from any map window) had assigned two daily
    section_ids (1337, 1706) to two different final topics each. valid_ids
    here is the FULL P2 universe (all non-fallback section ids), since
    reduce's job is to place every one of them into exactly one final topic."""
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
        print(
            f"  [reduce] {len(missing)} missing + {len(duplicated)} duplicated ({ratio:.1%}) exceeds "
            f"{BIWEEKLY_GROUPING_RATIO_THRESHOLD:.0%} - retrying once."
        )
        retry_topics, retry_usage = call_reduce_once(client, user_content)
        usages.append(retry_usage)
        retry_missing, retry_duplicated, retry_ratio = compute_stage1_problem_ratio(
            retry_topics, valid_ids, key="section_ids"
        )
        if retry_ratio < ratio:
            print(f"    retry improved ({ratio:.1%} -> {retry_ratio:.1%}) - using the retry result.")
            topics, missing, duplicated, ratio = retry_topics, retry_missing, retry_duplicated, retry_ratio
        else:
            print(f"    retry did not improve ({ratio:.1%} -> {retry_ratio:.1%}) - keeping the original grouping.")
        if ratio > BIWEEKLY_GROUPING_RATIO_THRESHOLD:
            print(
                f"    *** QUALITY WARNING ***: still {ratio:.1%} after retry "
                f"({len(missing)} missing, {len(duplicated)} duplicated) - accepting as-is."
            )

    total_usage = {
        "input_tokens": sum(u["input_tokens"] for u in usages),
        "output_tokens": sum(u["output_tokens"] for u in usages),
    }
    print(f"  [reduce] -> {len(topics)} final topic(s), final: {len(missing)} missing, "
          f"{len(duplicated)} duplicated, output={total_usage['output_tokens']} tok across {len(usages)} call(s)")
    return topics, total_usage, retries


def main():
    parser = argparse.ArgumentParser(description="Biweekly Stage 1 map-reduce dry-run.")
    parser.add_argument("--start", default=WINDOW_START, help="Period start date, YYYY-MM-DD (default: P2's start).")
    parser.add_argument("--end", default=WINDOW_END, help="Period end date, YYYY-MM-DD (default: P2's end).")
    args = parser.parse_args()
    window_start, window_end = args.start, args.end

    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, report_date, topic_label_en, comparison_text_en
        FROM report_sections
        WHERE report_date BETWEEN ? AND ? AND category != 'additional_coverage'
        ORDER BY report_date, id
        """,
        (window_start, window_end),
    ).fetchall()
    conn.close()

    sections_by_id = {r["id"]: r for r in rows}
    rows_by_date: dict[str, list] = {}
    for r in rows:
        rows_by_date.setdefault(r["report_date"], []).append(r)

    print(f"Biweekly stage-1 dry-run: {len(rows)} non-fallback sections across {len(rows_by_date)} day(s) "
          f"({window_start}..{window_end}).")

    client = anthropic.Anthropic()

    print("\n--- building map windows (token-budgeted, target "
          f"{TARGET_TOKENS_PER_MAP_WINDOW} tok/window) ---")
    windows = build_windows(client, rows_by_date)
    for i, dates in enumerate(windows, 1):
        n_sections = sum(len(rows_by_date[d]) for d in dates)
        print(f"  window {i}: {dates[0]}..{dates[-1]} ({len(dates)} day(s), {n_sections} sections)")

    print("\n--- running map calls ---")
    map_results = []
    total_map_usage = {"input_tokens": 0, "output_tokens": 0}
    total_map_retries = 0
    retry_log = []
    for i, dates in enumerate(windows, 1):
        topics, usage, retries = run_map(client, i, dates, rows_by_date)
        label = f"W{i}({dates[0]}..{dates[-1]})"
        map_results.append((label, topics))
        total_map_usage["input_tokens"] += usage["input_tokens"]
        total_map_usage["output_tokens"] += usage["output_tokens"]
        total_map_retries += retries
        if retries:
            retry_log.append(f"map window {i} ({dates[0]}..{dates[-1]}): retried {retries}x")

    # Sanity check: every section id assigned exactly once across all map outputs.
    all_assigned = []
    for _, topics in map_results:
        for t in topics:
            all_assigned.extend(t["section_ids"])
    missing = set(sections_by_id) - set(all_assigned)
    dupes = [x for x in set(all_assigned) if all_assigned.count(x) > 1]
    print(f"\n  map coverage check: {len(set(all_assigned))}/{len(sections_by_id)} ids assigned, "
          f"{len(missing)} missing, {len(dupes)} duplicated.")
    if missing:
        print(f"  missing ids: {sorted(missing)[:20]}{' ...' if len(missing) > 20 else ''}")
    if dupes:
        print(f"  duplicated ids (across map windows): {sorted(dupes)}")

    print("\n--- running reduce call ---")
    final_topics, reduce_usage, reduce_retries = run_reduce(client, map_results, sections_by_id)
    if reduce_retries:
        retry_log.append(f"reduce: retried {reduce_retries}x")
    total_retries = total_map_retries + reduce_retries
    print(f"\n  retry summary: {total_retries} total retr{'y' if total_retries==1 else 'ies'} fired"
          + (f" - {'; '.join(retry_log)}" if retry_log else " - none."))

    # Coverage check on the final merged list too.
    final_assigned = []
    for t in final_topics:
        final_assigned.extend(t["section_ids"])
    final_missing = set(sections_by_id) - set(final_assigned)
    final_dupes = [x for x in set(final_assigned) if final_assigned.count(x) > 1]

    # Distinct-day-count per final topic - the open assumption to check.
    enriched = []
    for t in final_topics:
        dates_covered = sorted({sections_by_id[i]["report_date"] for i in t["section_ids"] if i in sections_by_id})
        enriched.append({
            "topic_label_en": t["topic_label_en"],
            "n_sections": len(t["section_ids"]),
            "n_distinct_days": len(dates_covered),
            "dates_covered": dates_covered,
            "section_ids": t["section_ids"],
        })
    enriched.sort(key=lambda x: -x["n_distinct_days"])

    print(f"\n=== FINAL CROSS-P2 TOPIC LIST ({len(final_topics)} topics) ===")
    for e in enriched:
        print(f"[{e['n_distinct_days']}d / {e['n_sections']} sec] {e['topic_label_en']}  -> {e['dates_covered']}")

    print(f"\nfinal coverage check: {len(set(final_assigned))}/{len(sections_by_id)} ids assigned, "
          f"{len(final_missing)} missing, {len(final_dupes)} duplicated.")
    if final_dupes:
        print(f"  final duplicated ids: {sorted(final_dupes)}")
    # The two concrete section_ids the 2026-10-07 diagnostic found reduce had
    # assigned to two different final topics (1337, 1706, both P2-only ids) -
    # only meaningful when this run's own valid_ids actually cover them, since
    # this script is now reused for other periods too (P1, P3, ...) where
    # these specific ids don't exist and would trivially print "resolved".
    for known_id in (1337, 1706):
        if known_id not in sections_by_id:
            continue
        hit = known_id in final_dupes
        print(f"  known-problem section {known_id}: {'STILL duplicated' if hit else 'resolved (no longer duplicated)'}")

    day_counts = [e["n_distinct_days"] for e in enriched]
    if day_counts:
        print(f"\ndistinct-day-count distribution across final topics: "
              f"max={max(day_counts)}, mean={sum(day_counts)/len(day_counts):.2f}, "
              f"topics spanning >=5 days: {sum(1 for x in day_counts if x >= 5)}, "
              f">=8 days: {sum(1 for x in day_counts if x >= 8)}")
    else:
        # Guards against a crash that actually happened (2026-10-08, P3 run):
        # reduce returned 0 final topics (hit max_tokens before completing a
        # tool_use block, on both the original attempt and the retry) and the
        # script died here on max() of an empty list - BEFORE the output file
        # below was ever written, silently throwing away the already-good,
        # already-paid-for map results along with it. Reduce's own max_tokens
        # was raised separately (see call_reduce_once) as the likely real fix,
        # but this guard stays regardless - a future run()-time anomaly should
        # never again be able to discard completed map work by crashing before
        # the file write.
        print("\n*** REDUCE PRODUCED 0 FINAL TOPICS *** - map results are still written below for "
              "inspection/retry, but there is no final topic list this run.")

    total_cost_tokens = {
        "map_input": total_map_usage["input_tokens"],
        "map_output": total_map_usage["output_tokens"],
        "reduce_input": reduce_usage["input_tokens"],
        "reduce_output": reduce_usage["output_tokens"],
    }
    print(f"\ntotal usage: {total_cost_tokens}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"biweekly_stage1_dryrun_{window_start}_{window_end}.json"
    out_path.write_text(
        json.dumps(
            {
                "window": [window_start, window_end],
                "biweekly_grouping_ratio_threshold": BIWEEKLY_GROUPING_RATIO_THRESHOLD,
                # Raw per-window map output persisted (not just dates) so a
                # specific duplicated/missing id can be traced back to which
                # window produced it, without re-running the API calls -
                # added 2026-10-07 after not being able to answer that
                # question from the previous run's saved file.
                "map_windows": [
                    {"dates": d, "topics": map_results[idx][1]} for idx, d in enumerate(windows)
                ],
                "retries_fired": {"map": total_map_retries, "reduce": reduce_retries, "log": retry_log},
                "final_topics": enriched,
                "usage": total_cost_tokens,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
