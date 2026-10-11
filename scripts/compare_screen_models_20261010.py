"""One-off controlled experiment (2026-10-10): Haiku 4.5 vs. Haiku 5.5 for
src/analysis/screen.py's Stage 1 relevance screening.

Retrospective only - runs BOTH models fresh against a sample of pages that
already have a known/verified is_relevant label in page_screening (the
existing DB value is ground truth), and compares each model's live verdict
against that ground truth. Does not touch the production screening flow or
write anything back to tracker.db. See PROJECT_LOG 2026-10-10 for the full
write-up; see src/analysis/screen.py's MODEL constant for the production
default (unchanged by this script).

Usage: python -m scripts.compare_screen_models_20261010
"""
import json
import sys
import time

import anthropic
from dotenv import load_dotenv

from src.analysis.screen import SYSTEM_PROMPT, SCREEN_TOOL
from src.common.db import get_connection

sys.stdout.reconfigure(encoding="utf-8")

HAIKU_45 = "claude-haiku-4-5-20251001"
HAIKU_55 = "claude-haiku-5-5"

# Verified official pricing (claude.com/pricing, checked 2026-10-10) - Haiku 5.5's
# <=100K-token tier applies to every single-page screening call in this pipeline.
PRICING = {
    HAIKU_45: {"input": 1.00, "output": 5.00},
    HAIKU_55: {"input": 0.10, "output": 0.50},
}

# The 4 known, manually-verified borderline cases from PROJECT_LOG (Telegraph
# "Court & Social" pages: real obituaries + a "100 years ago" historical-
# nostalgia reprint - all 4 were Stage-1 false positives, corrected to
# is_relevant=0 by hand) - forced into the sample regardless of random draw.
KNOWN_BORDERLINE = [
    (2, 20),
    (14, 24),
    (20, 24),
    (27, 23),
]

SAMPLE_SIZE_PER_CLASS = 48  # + the 4 known borderline cases = 100 total


def fetch_sample(conn):
    cur = conn.cursor()
    rows = []
    seen = set()

    for file_id, page_number in KNOWN_BORDERLINE:
        cur.execute(
            """SELECT ps.file_id, ps.page_number, ps.is_relevant, ep.raw_text
               FROM page_screening ps
               JOIN extracted_pages ep ON ep.file_id = ps.file_id AND ep.page_number = ps.page_number
               WHERE ps.file_id = ? AND ps.page_number = ?""",
            (file_id, page_number),
        )
        row = cur.fetchone()
        if row:
            rows.append({"file_id": row[0], "page_number": row[1], "ground_truth": bool(row[2]), "raw_text": row[3], "known_borderline": True})
            seen.add((row[0], row[1]))

    for label in (1, 0):
        cur.execute(
            """SELECT ps.file_id, ps.page_number, ps.is_relevant, ep.raw_text
               FROM page_screening ps
               JOIN extracted_pages ep ON ep.file_id = ps.file_id AND ep.page_number = ps.page_number
               WHERE ps.is_relevant = ? AND length(ep.raw_text) > 100
               ORDER BY RANDOM()""",
            (label,),
        )
        count = 0
        for row in cur.fetchall():
            if (row[0], row[1]) in seen:
                continue
            rows.append({"file_id": row[0], "page_number": row[1], "ground_truth": bool(row[2]), "raw_text": row[3], "known_borderline": False})
            seen.add((row[0], row[1]))
            count += 1
            if count >= SAMPLE_SIZE_PER_CLASS:
                break

    return rows


def screen_with_model(client, raw_text, model):
    """Returns (is_relevant, reasoning, usage_dict, refusal_category_or_None)."""
    try:
        response = client.messages.create(
            model=model,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            tools=[SCREEN_TOOL],
            tool_choice={"type": "tool", "name": "record_screening"},
            messages=[{"role": "user", "content": raw_text}],
        )
    except anthropic.BadRequestError as e:
        return None, f"BadRequestError: {e.message}", None, "api_error"

    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }

    if response.stop_reason == "refusal":
        category = getattr(response.stop_details, "category", None) if response.stop_details else None
        return None, f"refusal (category={category})", usage, category or "unknown"

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        return None, f"no tool_use block (stop_reason={response.stop_reason})", usage, None

    return bool(tool_use.input["is_relevant"]), tool_use.input["reasoning"], usage, None


def main():
    load_dotenv()
    conn = get_connection()
    sample = fetch_sample(conn)
    conn.close()

    print(f"Sample size: {len(sample)} ({sum(1 for r in sample if r['known_borderline'])} known-borderline, "
          f"{sum(1 for r in sample if r['ground_truth'])} relevant, {sum(1 for r in sample if not r['ground_truth'])} not-relevant)")

    client = anthropic.Anthropic()
    results = []

    for i, page in enumerate(sample):
        row = {"file_id": page["file_id"], "page_number": page["page_number"],
               "ground_truth": page["ground_truth"], "known_borderline": page["known_borderline"]}
        for model_name, model_id in (("haiku45", HAIKU_45), ("haiku55", HAIKU_55)):
            is_relevant, reasoning, usage, refusal = screen_with_model(client, page["raw_text"], model_id)
            row[f"{model_name}_is_relevant"] = is_relevant
            row[f"{model_name}_reasoning"] = reasoning
            row[f"{model_name}_usage"] = usage
            row[f"{model_name}_refusal"] = refusal
            time.sleep(0.05)
        results.append(row)
        if (i + 1) % 10 == 0:
            print(f"  ...{i + 1}/{len(sample)} done")

    with open("scripts/output/compare_screen_models_20261010_raw.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # --- Analysis ---
    def stats_for(model_name):
        tp = fp = tn = fn = refusals = errors = 0
        total_in = total_out = 0
        mismatches = []
        for r in results:
            gt = r["ground_truth"]
            pred = r[f"{model_name}_is_relevant"]
            if r[f"{model_name}_refusal"] == "api_error":
                errors += 1
                continue
            if r[f"{model_name}_refusal"] is not None:
                refusals += 1
                continue
            usage = r[f"{model_name}_usage"]
            if usage:
                total_in += usage["input_tokens"]
                total_out += usage["output_tokens"]
            if pred is True and gt is True:
                tp += 1
            elif pred is True and gt is False:
                fp += 1
                mismatches.append(r)
            elif pred is False and gt is False:
                tn += 1
            elif pred is False and gt is True:
                fn += 1
                mismatches.append(r)
        scored = tp + fp + tn + fn
        match_rate = (tp + tn) / scored * 100 if scored else 0
        cost = (total_in / 1_000_000 * PRICING[HAIKU_45 if model_name == "haiku45" else HAIKU_55]["input"]
                + total_out / 1_000_000 * PRICING[HAIKU_45 if model_name == "haiku45" else HAIKU_55]["output"])
        return {
            "tp": tp, "fp": fp, "tn": tn, "fn": fn, "refusals": refusals, "errors": errors,
            "match_rate": match_rate, "total_input_tokens": total_in, "total_output_tokens": total_out,
            "cost_usd": cost, "mismatches": mismatches,
        }

    s45 = stats_for("haiku45")
    s55 = stats_for("haiku55")

    print("\n=== Haiku 4.5 ===")
    print(f"  TP={s45['tp']} FP={s45['fp']} TN={s45['tn']} FN={s45['fn']} refusals={s45['refusals']} errors={s45['errors']}")
    print(f"  match rate: {s45['match_rate']:.1f}%")
    print(f"  tokens: {s45['total_input_tokens']} in / {s45['total_output_tokens']} out")
    print(f"  cost: ${s45['cost_usd']:.4f}")

    print("\n=== Haiku 5.5 ===")
    print(f"  TP={s55['tp']} FP={s55['fp']} TN={s55['tn']} FN={s55['fn']} refusals={s55['refusals']} errors={s55['errors']}")
    print(f"  match rate: {s55['match_rate']:.1f}%")
    print(f"  tokens: {s55['total_input_tokens']} in / {s55['total_output_tokens']} out")
    print(f"  cost: ${s55['cost_usd']:.4f}")

    print(f"\nCost ratio (5.5 / 4.5): {s55['cost_usd'] / s45['cost_usd'] * 100:.1f}% of Haiku 4.5's cost on this sample")

    print("\n--- Known-borderline (Court & Social) cases ---")
    for r in results:
        if r["known_borderline"]:
            print(f"  file={r['file_id']} page={r['page_number']} ground_truth={r['ground_truth']}")
            print(f"    4.5: is_relevant={r['haiku45_is_relevant']} | {r['haiku45_reasoning']}")
            print(f"    5.5: is_relevant={r['haiku55_is_relevant']} | {r['haiku55_reasoning']}")

    print("\n--- Haiku 4.5 mismatches ---")
    for r in s45["mismatches"]:
        print(f"  file={r['file_id']} page={r['page_number']} ground_truth={r['ground_truth']} predicted={r['haiku45_is_relevant']} | {r['haiku45_reasoning']}")

    print("\n--- Haiku 5.5 mismatches ---")
    for r in s55["mismatches"]:
        print(f"  file={r['file_id']} page={r['page_number']} ground_truth={r['ground_truth']} predicted={r['haiku55_is_relevant']} | {r['haiku55_reasoning']}")


if __name__ == "__main__":
    main()
