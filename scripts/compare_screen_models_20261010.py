"""One-off controlled experiments for src/analysis/screen.py's Stage 1
relevance screening.

Retrospective only - runs model(s) fresh against a sample of pages that
already have a known/verified is_relevant label in page_screening (the
existing DB value is ground truth), and compares each model's live verdict
against that ground truth. Pure read-only against tracker.db throughout -
never writes anything back. Does not touch the production screening flow;
see src/analysis/screen.py's MODEL constant for the production default
(unchanged by either experiment below).

Two independent experiments live in this one file (extended, not rewritten):

1. Haiku 4.5 vs. Haiku 5.5 (2026-10-10, see PROJECT_LOG 4.88) - default when
   run with no flags:
       python -m scripts.compare_screen_models_20261010

2. Haiku 4.5 vs. Gemini 2.5 Flash (2026-10-12) - a cross-vendor stress test
   on an adversarial + balanced sample. Verifies the Gemini model id against
   the live Models API first (never assumed). Defaults to a free dry run
   (model verification + dataset composition only, no generation calls on
   either vendor) - pass --execute to actually spend money on the full
   comparison:
       python -m scripts.compare_screen_models_20261010 --vs gemini
       python -m scripts.compare_screen_models_20261010 --vs gemini --execute
"""
import argparse
import json
import os
import sys
import time

import anthropic
from dotenv import load_dotenv
from google import genai
from google.genai import types

from src.analysis.screen import SYSTEM_PROMPT, SCREEN_TOOL
from src.common.db import get_connection

sys.stdout.reconfigure(encoding="utf-8")

HAIKU_45 = "claude-haiku-4-5-20251001"
HAIKU_55 = "claude-haiku-5-5"

# models/gemini-2.5-flash matched the external advisor's original recommendation
# and was listed as available by models.list() (generateContent included in its
# supported_actions) - but a live generateContent call against it 404'd for
# every single page in the first run of this experiment (2026-10-12), with an
# explicit API error: "This model models/gemini-2.5-flash is no longer
# available to new users. Please update your code to use
# models/gemini-3.8-flash." I.e. models.list() does not reliably reflect real
# generation availability for an account - confirm with an actual call, not
# just a listing. Switched to gemini-3.8-flash per that explicit, documented
# API-sourced recommendation (not a preference pick among the many newer
# variants also listed) - approved by the user before re-running.
GEMINI_MODEL = "models/gemini-3.8-flash"

# Verified official pricing (claude.com/pricing, checked 2026-10-10; ai.google.dev/
# gemini-api/docs/pricing, checked 2026-10-12 - standard/non-batch tier, which is
# what a one-call-per-page loop like this one actually uses) - Haiku 5.5's
# <=100K-token tier applies to every single-page screening call in this pipeline.
# Gemini 3.8 Flash's rate is time-boxed by Google ($0.75/$3.75 through
# 2026-12-31, doubling to $1.50/$7.50 on 2027-01-01) - today (2026-10-12) is
# within the current-rate window.
PRICING = {
    HAIKU_45: {"input": 1.00, "output": 5.00},
    HAIKU_55: {"input": 0.10, "output": 0.50},
    GEMINI_MODEL: {"input": 0.75, "output": 3.75},
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


# --- Experiment 2: Haiku 4.5 vs. Gemini 2.5 Flash (2026-10-12) ---

def verify_gemini_model(preferred=GEMINI_MODEL):
    """Confirms the exact model id is live on this account via models.list()
    (a metadata call, not a generation call - effectively free, not the
    "costs money" step) rather than assuming the constant above is still
    valid. Raises if it's gone, so the comparison never silently runs against
    the wrong id."""
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    available = {m.name for m in client.models.list()}
    if preferred not in available:
        flash_variants = sorted(m for m in available if "flash" in m.lower())
        raise RuntimeError(
            f"{preferred} is not available to this account. Available Flash models: {flash_variants}"
        )
    return client, preferred


def screen_with_gemini(client, raw_text, model):
    """Mirrors screen_with_model()'s (is_relevant, reasoning, usage, refusal)
    return shape. Reuses SCREEN_TOOL's input_schema directly as the response
    JSON schema (response_json_schema accepts JSON Schema's type/properties/
    required/additionalProperties - all present on SCREEN_TOOL - per the
    installed google-genai SDK's GenerateContentConfig field docs) so the
    extraction contract is byte-identical to the Anthropic tool call, not a
    hand-translated approximation."""
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_json_schema=SCREEN_TOOL["input_schema"],
        max_output_tokens=300,
        # Disabled explicitly (0 = DISABLED, per ThinkingConfig's own field docs)
        # - gemini-3.8-flash is a thinking-capable model and defaults to spending
        # part of max_output_tokens on hidden thinking tokens, which truncated
        # the visible JSON mid-output in an initial single-page test (2026-10-12,
        # output was cut off after 7 tokens: "Here is the JSON requ"). Screening
        # is meant to be the fast/cheap net (mirrors Haiku 4.5's plain tool call,
        # no extended thinking there either) - not where reasoning budget belongs.
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
    try:
        response = client.models.generate_content(model=model, contents=raw_text, config=config)
    except Exception as e:
        return None, f"error: {e}", None, "api_error"

    usage = None
    if response.usage_metadata:
        usage = {
            "input_tokens": response.usage_metadata.prompt_token_count or 0,
            "output_tokens": response.usage_metadata.candidates_token_count or 0,
        }

    if not response.text:
        finish_reason = None
        if response.candidates:
            finish_reason = response.candidates[0].finish_reason
        return None, f"no text in response (finish_reason={finish_reason})", usage, "no_text"

    try:
        parsed = json.loads(response.text)
    except json.JSONDecodeError:
        return None, f"invalid JSON: {response.text[:200]!r}", usage, "bad_json"

    return bool(parsed["is_relevant"]), parsed.get("reasoning", ""), usage, None


def fetch_nostalgia_failure_pages(conn):
    """The 4 nostalgia/history pages identified during the Haiku 4.5 vs. 5.5
    experiment (KNOWN_BORDERLINE above; Telegraph "Court & Social": real
    obituaries + a "100 years ago" historical-nostalgia reprint). All 4 are
    ground_truth=False, and all 4 were false positives for Haiku 5.5 (verified
    against scripts/output/compare_screen_models_20261010_raw.json). Reused
    here as an adversarial subset, not a fresh random draw - a candidate model
    that also fails these reproduces a known failure mode, not a coincidence."""
    rows = []
    cur = conn.cursor()
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
            rows.append({"file_id": row[0], "page_number": row[1], "ground_truth": bool(row[2]),
                         "raw_text": row[3], "group": "nostalgia_failure", "published": False})
    return rows


def fetch_balanced_published_sample(conn, seen, n_per_class=35):
    """n_per_class pages marked is_relevant=1 in Stage 1 AND that actually
    yielded a published article - joined through articles -> report_section_
    articles, not just present in `articles` (excludes the documented
    is_relevant=1-but-never-published orphan gap, see CLAUDE.md's "אין
    להניח 0 שורות = טרם עובד" / orphan_review.py) - so "yielded a published
    article" means confirmed-published, not merely analyzed. Plus
    n_per_class marked is_relevant=0 (length>100 only, same floor the
    original Haiku 4.5 vs 5.5 sample used, to exclude near-empty pages)."""
    rows = []
    cur = conn.cursor()

    cur.execute(
        """SELECT DISTINCT ps.file_id, ps.page_number, ep.raw_text
           FROM page_screening ps
           JOIN articles a ON a.file_id = ps.file_id AND a.page_number = ps.page_number
           JOIN report_section_articles rsa ON rsa.article_id = a.id
           JOIN extracted_pages ep ON ep.file_id = ps.file_id AND ep.page_number = ps.page_number
           WHERE ps.is_relevant = 1
           ORDER BY RANDOM()"""
    )
    count = 0
    for row in cur.fetchall():
        if (row[0], row[1]) in seen:
            continue
        rows.append({"file_id": row[0], "page_number": row[1], "ground_truth": True,
                     "raw_text": row[2], "group": "balanced_sample", "published": True})
        seen.add((row[0], row[1]))
        count += 1
        if count >= n_per_class:
            break

    cur.execute(
        """SELECT ps.file_id, ps.page_number, ep.raw_text
           FROM page_screening ps
           JOIN extracted_pages ep ON ep.file_id = ps.file_id AND ep.page_number = ps.page_number
           WHERE ps.is_relevant = 0 AND length(ep.raw_text) > 100
           ORDER BY RANDOM()"""
    )
    count = 0
    for row in cur.fetchall():
        if (row[0], row[1]) in seen:
            continue
        rows.append({"file_id": row[0], "page_number": row[1], "ground_truth": False,
                     "raw_text": row[2], "group": "balanced_sample", "published": False})
        seen.add((row[0], row[1]))
        count += 1
        if count >= n_per_class:
            break

    return rows


def build_stress_test_dataset(conn):
    nostalgia = fetch_nostalgia_failure_pages(conn)
    seen = {(r["file_id"], r["page_number"]) for r in nostalgia}
    balanced = fetch_balanced_published_sample(conn, seen, n_per_class=35)
    return nostalgia + balanced


def report_dataset_composition(dataset):
    nostalgia = [r for r in dataset if r["group"] == "nostalgia_failure"]
    balanced = [r for r in dataset if r["group"] == "balanced_sample"]
    balanced_pos = [r for r in balanced if r["ground_truth"]]
    balanced_neg = [r for r in balanced if not r["ground_truth"]]

    print(f"\n=== Stress-test dataset composition ({len(dataset)} pages total) ===")
    print(f"  Nostalgia/history failure pages (adversarial, from Haiku 5.5 experiment): {len(nostalgia)}")
    for r in nostalgia:
        print(f"    file={r['file_id']} page={r['page_number']} ground_truth={r['ground_truth']}")
    print(f"  Balanced sample: {len(balanced)} ({len(balanced_pos)} relevant+published, {len(balanced_neg)} not-relevant)")
    print(f"    file_id range (published): {min((r['file_id'] for r in balanced_pos), default='-')}"
          f"-{max((r['file_id'] for r in balanced_pos), default='-')}")
    print(f"    file_id range (not-relevant): {min((r['file_id'] for r in balanced_neg), default='-')}"
          f"-{max((r['file_id'] for r in balanced_neg), default='-')}")
    dupes = len(dataset) - len({(r["file_id"], r["page_number"]) for r in dataset})
    print(f"  Duplicate (file_id, page_number) pairs across groups: {dupes} (should be 0)")


def run_haiku_vs_gemini(execute: bool):
    load_dotenv()

    gemini_client, gemini_model = verify_gemini_model()
    print(f"Verified Gemini model (live models.list() call): {gemini_model}")

    conn = get_connection()
    dataset = build_stress_test_dataset(conn)
    conn.close()
    report_dataset_composition(dataset)

    if not execute:
        print("\nDry run only (no generation calls made on either vendor, no money spent). "
              "Re-run with --execute to run the full paid comparison.")
        return

    anthropic_client = anthropic.Anthropic()
    results = []
    for i, page in enumerate(dataset):
        row = {"file_id": page["file_id"], "page_number": page["page_number"],
               "ground_truth": page["ground_truth"], "group": page["group"],
               "published": page["published"]}

        t0 = time.perf_counter()
        is_rel, reasoning, usage, refusal = screen_with_model(anthropic_client, page["raw_text"], HAIKU_45)
        row["haiku45_latency_s"] = time.perf_counter() - t0
        row["haiku45_is_relevant"] = is_rel
        row["haiku45_reasoning"] = reasoning
        row["haiku45_usage"] = usage
        row["haiku45_refusal"] = refusal

        t0 = time.perf_counter()
        is_rel, reasoning, usage, refusal = screen_with_gemini(gemini_client, page["raw_text"], gemini_model)
        row["gemini_latency_s"] = time.perf_counter() - t0
        row["gemini_is_relevant"] = is_rel
        row["gemini_reasoning"] = reasoning
        row["gemini_usage"] = usage
        row["gemini_refusal"] = refusal

        results.append(row)
        time.sleep(0.05)
        if (i + 1) % 10 == 0:
            print(f"  ...{i + 1}/{len(dataset)} done")

    with open("scripts/output/compare_screen_haiku_vs_gemini_20261012_raw.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    def cost_for(model_id, total_in, total_out):
        p = PRICING[model_id]
        return total_in / 1_000_000 * p["input"] + total_out / 1_000_000 * p["output"]

    scored = [r for r in results if r["haiku45_refusal"] is None and r["gemini_refusal"] is None]
    concordant = sum(1 for r in scored if r["haiku45_is_relevant"] == r["gemini_is_relevant"])
    concordance_rate = concordant / len(scored) * 100 if scored else 0

    published = [r for r in results if r["published"]]
    haiku_fn_published = [r for r in published if r["haiku45_refusal"] is None and r["haiku45_is_relevant"] is False]
    gemini_fn_published = [r for r in published if r["gemini_refusal"] is None and r["gemini_is_relevant"] is False]

    nostalgia = [r for r in results if r["group"] == "nostalgia_failure"]
    haiku_fp_nostalgia = [r for r in nostalgia if r["haiku45_refusal"] is None and r["haiku45_is_relevant"] is True]
    gemini_fp_nostalgia = [r for r in nostalgia if r["gemini_refusal"] is None and r["gemini_is_relevant"] is True]

    haiku_in = sum(r["haiku45_usage"]["input_tokens"] for r in results if r["haiku45_usage"])
    haiku_out = sum(r["haiku45_usage"]["output_tokens"] for r in results if r["haiku45_usage"])
    gemini_in = sum(r["gemini_usage"]["input_tokens"] for r in results if r["gemini_usage"])
    gemini_out = sum(r["gemini_usage"]["output_tokens"] for r in results if r["gemini_usage"])
    haiku_latencies = [r["haiku45_latency_s"] for r in results]
    gemini_latencies = [r["gemini_latency_s"] for r in results]

    print(f"\n=== Concordance ===")
    print(f"  {concordant}/{len(scored)} scored pages agree ({concordance_rate:.1f}%)")

    print(f"\n=== False negatives on confirmed-published articles (zero-tolerance gate) ===")
    print(f"  Haiku 4.5: {len(haiku_fn_published)}/{len(published)}")
    for r in haiku_fn_published:
        print(f"    file={r['file_id']} page={r['page_number']} | {r['haiku45_reasoning']}")
    print(f"  Gemini 2.5 Flash: {len(gemini_fn_published)}/{len(published)}")
    for r in gemini_fn_published:
        print(f"    file={r['file_id']} page={r['page_number']} | {r['gemini_reasoning']}")

    print(f"\n=== False positives on the nostalgia/history subset ({len(nostalgia)} pages) ===")
    print(f"  Haiku 4.5: {len(haiku_fp_nostalgia)}/{len(nostalgia)}")
    print(f"  Gemini 2.5 Flash: {len(gemini_fp_nostalgia)}/{len(nostalgia)}")

    print(f"\n=== Latency ===")
    print(f"  Haiku 4.5: mean={sum(haiku_latencies)/len(haiku_latencies):.2f}s "
          f"min={min(haiku_latencies):.2f}s max={max(haiku_latencies):.2f}s")
    print(f"  Gemini 2.5 Flash: mean={sum(gemini_latencies)/len(gemini_latencies):.2f}s "
          f"min={min(gemini_latencies):.2f}s max={max(gemini_latencies):.2f}s")

    print(f"\n=== Estimated cost on this {len(dataset)}-page sample ===")
    print(f"  Haiku 4.5: ${cost_for(HAIKU_45, haiku_in, haiku_out):.4f} ({haiku_in} in / {haiku_out} out tokens)")
    print(f"  Gemini 2.5 Flash: ${cost_for(GEMINI_MODEL, gemini_in, gemini_out):.4f} ({gemini_in} in / {gemini_out} out tokens)")

    print(f"\n=== Discrepancy table (all disagreements) ===")
    disagreements = [r for r in scored if r["haiku45_is_relevant"] != r["gemini_is_relevant"]]
    for r in disagreements:
        print(f"  file={r['file_id']} page={r['page_number']} group={r['group']} ground_truth={r['ground_truth']}")
        print(f"    Haiku 4.5:  is_relevant={r['haiku45_is_relevant']} | {r['haiku45_reasoning']}")
        print(f"    Gemini 2.5: is_relevant={r['gemini_is_relevant']} | {r['gemini_reasoning']}")

    non_scored = [r for r in results if r not in scored]
    if non_scored:
        print(f"\n=== Excluded from concordance (refusal/error on one side): {len(non_scored)} ===")
        for r in non_scored:
            print(f"  file={r['file_id']} page={r['page_number']} haiku45_refusal={r['haiku45_refusal']} gemini_refusal={r['gemini_refusal']}")


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
    parser = argparse.ArgumentParser()
    parser.add_argument("--vs", choices=["haiku55", "gemini"], default="haiku55",
                         help="Which experiment to run (default: haiku55, the original 2026-10-10 comparison).")
    parser.add_argument("--execute", action="store_true",
                         help="For --vs gemini only: actually run the paid comparison. "
                              "Without it, only verifies the model and reports dataset composition (free).")
    args = parser.parse_args()

    if args.vs == "gemini":
        run_haiku_vs_gemini(execute=args.execute)
    else:
        main()
