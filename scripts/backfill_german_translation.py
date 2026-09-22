"""One-off backfill: German rewrite for all existing report_sections (2026-09-22).

Adds topic_label_de/comparison_text_de to every existing section, in the same register and
terminology as src/common/about_content.py's German "de" entry (passed to the model as a style
anchor) - a native-sounding rewrite, not a mechanical sentence-by-sentence translation. Source
language: English (topic_label_en/comparison_text_en) - the same choice already measured and
approved in the cost inquiry that preceded this (see PROJECT_LOG). Going forward (next report
onward), German is generated natively in Stage 2 of synthesize.py, alongside Hebrew/English in
the same call - this script only backfills the archive that predates that change.

Batching: a single non-streaming call for a whole report overflows the ~16,000 output-token
ceiling once a report has more than ~20 sections (measured in the cost inquiry - one attempt on a
37-section report hit the cap and returned nothing usable). Sections are grouped into batches of
BATCH_SIZE; if a batch still hits max_tokens or comes back incomplete, it is split in half and
retried (recursively) - this makes the batch size an optimization, not a correctness assumption,
so it's safe even for the archive's largest report (2026-08-28, 150 sections).

Idempotent and resumable: a report already fully filled (every section has both German fields) is
skipped; if the run is interrupted, rerunning it only pays for the reports/batches not yet done,
because each report's German text is written to the DB as soon as that report's batches complete
and pass a completeness check - no all-or-nothing transaction across the whole archive.

Usage: python -m scripts.backfill_german_translation [--date YYYY-MM-DD]
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from src.common.about_content import CONTENT
from src.common.db import get_connection, init_db
from src.reporting.synthesize import MODEL

sys.stdout.reconfigure(encoding="utf-8")

BATCH_SIZE = 18
CONCURRENCY = 6  # same as synthesize.py's STAGE2_CONCURRENCY - already-measured-safe rate
OUT_LOG = Path(__file__).resolve().parents[1] / "data" / "processed" / "german_backfill_cost_log.json"

# A concrete excerpt of the German About document, as a register/terminology anchor - not a
# rulebook restated in the abstract. The model is told explicitly to match its vocabulary
# (Meinungsbeitrag, Vergleich, Quelle/Zeitung, Bericht) and its formal-but-readable register.
STYLE_ANCHOR = CONTENT["de"]["sections"][0]["blocks"][0][1]

SYSTEM_PROMPT = f"""You are rewriting existing geopolitical news-comparison report sections from English into German, for a German-reading edition of this project's daily reports (which already exist in Hebrew and English). This is a native-sounding German rewrite - not a mechanical, sentence-by-sentence translation - matching the register, vocabulary, and idiomatic fluency already established for this project's German-language material. Here is a real excerpt of that established German house style, for register and terminology reference:

"{STYLE_ANCHOR}"

Match that register: formal but readable, professional-journalistic German (Hochsprache) suitable for a serious news/analysis publication. Prefer its established terms where they fit naturally - e.g. "Meinungsbeitrag(e)" for an opinion piece, "Vergleich"/"vergleichend" for the cross-source comparison, "Quelle"/"Zeitung"/"Blatt" for a source/newspaper, "Bericht" for the report itself - without forcing a term where it reads unnaturally.

Rules:
- Newspaper names: whenever a source is named, use EXACTLY one of these forms, in their original Latin script - never transliterate, translate, abbreviate, or Germanize them: "The Guardian", "The Daily Telegraph", "Süddeutsche Zeitung", "Die Welt", "The New York Times International", "The Wall Street Journal", "Los Angeles Times", "USA Today", "The Washington Post", "The Economist", "Der Spiegel".
- German grammar: standard, formal written German. Pay particular attention to article/adjective/case agreement (der/die/das and declension) and noun-number agreement. Reread each German sentence for this kind of agreement error before finalizing it.
- Preserve the substantive content, structure, and comparative framing of each section exactly - do not add, omit, or soften claims, and do not add a translator's note.
- topic_label_de should read as a natural German headline/topic label of similar length and register to the English one, not a literal word-for-word rendering.

You will be given N sections, each with its own id, from one batch of one report. You MUST return exactly N entries in `sections`, one per id given, covering every single id with no omissions and no extras. Call record_translations exactly once, with all N entries in that one call."""

TOOL = {
    "name": "record_translations",
    "description": "Record the German rewrite of every section given in this call.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "topic_label_de": {"type": "string"},
                        "comparison_text_de": {"type": "string"},
                    },
                    "required": ["id", "topic_label_de", "comparison_text_de"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["sections"],
        "additionalProperties": False,
    },
    "strict": True,
}


def _call(client, report_date: str, batch: list) -> tuple[list, dict]:
    """One API call for one batch. Returns (translations, usage-dict). Never raises on a
    max-tokens/incomplete result - the caller decides whether to split and retry."""
    user_text = (
        f"Report date: {report_date}. This batch has exactly {len(batch)} sections; your output "
        f"must contain exactly {len(batch)} entries, one per id listed below.\n\n"
        + "\n\n".join(
            f"id={r['id']} | category={r['category']}\n"
            f"topic_label_en: {r['topic_label_en']}\n"
            f"comparison_text_en: {r['comparison_text_en']}"
            for r in batch
        )
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "record_translations"},
        messages=[{"role": "user", "content": user_text}],
    )
    u = response.usage
    usage = {
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
    }
    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    got = tool_use.input.get("sections", []) if tool_use else []
    return got, usage


def translate_batch(client, report_date: str, batch: list, depth: int = 0) -> tuple[list, list]:
    """Returns (translations, usage_log). Splits and retries on an incomplete/overflowing batch,
    AND on a real exception (a transient API error must not crash the whole run any more than an
    incomplete response does - both get the same split-and-retry treatment; only a batch that
    still fails at the recursion floor is a genuine, reported failure). Correctness (every id
    covered) comes from this, not from guessing the right batch size up front."""
    expected_ids = {r["id"] for r in batch}
    try:
        got, usage = _call(client, report_date, batch)
    except Exception as exc:
        if len(batch) == 1 or depth >= 6:
            raise RuntimeError(f"batch of {len(batch)} for {report_date} failed after {depth} splits: {exc}") from exc
        mid = len(batch) // 2
        print(f"    batch of {len(batch)} raised {exc!r} - splitting and retrying")
        left, left_usage = translate_batch(client, report_date, batch[:mid], depth + 1)
        right, right_usage = translate_batch(client, report_date, batch[mid:], depth + 1)
        return left + right, left_usage + right_usage  # no usage to record for the raised call itself
    got_ids = {t["id"] for t in got if isinstance(t, dict) and "id" in t}
    if got_ids == expected_ids and len(got) == len(batch):
        return got, [usage]
    if len(batch) == 1 or depth >= 6:
        raise RuntimeError(f"batch of {len(batch)} for {report_date} could not complete after {depth} splits "
                            f"(got {len(got_ids)}/{len(expected_ids)} ids)")
    mid = len(batch) // 2
    print(f"    batch of {len(batch)} incomplete ({len(got_ids)}/{len(expected_ids)}) - splitting and retrying")
    left, left_usage = translate_batch(client, report_date, batch[:mid], depth + 1)
    right, right_usage = translate_batch(client, report_date, batch[mid:], depth + 1)
    return left + right, [usage] + left_usage + right_usage  # keep the failed attempt's usage too - it was paid for


def cost_of(usage_list: list) -> float:
    return sum(u["input_tokens"] / 1e6 * 2.0 + u["output_tokens"] / 1e6 * 10.0 for u in usage_list)


def run(only_date: str | None = None) -> None:
    load_dotenv()
    conn = get_connection()
    init_db(conn)
    client = anthropic.Anthropic()

    dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT report_date FROM report_sections WHERE ? IS NULL OR report_date = ? ORDER BY report_date",
        (only_date, only_date),
    )]

    log = json.loads(OUT_LOG.read_text(encoding="utf-8")) if OUT_LOG.exists() else {"reports": {}}
    grand_total_cost = 0.0
    grand_total_sections = 0
    t_start = time.time()

    for report_date in dates:
        sections = conn.execute(
            "SELECT id, topic_label_en, comparison_text_en, category, topic_label_de, comparison_text_de "
            "FROM report_sections WHERE report_date = ? ORDER BY id",
            (report_date,),
        ).fetchall()
        if all(r["topic_label_de"] and r["comparison_text_de"] for r in sections):
            print(f"{report_date}: already backfilled ({len(sections)} sections) - skipped")
            continue

        t0 = time.time()
        batches = [sections[i:i + BATCH_SIZE] for i in range(0, len(sections), BATCH_SIZE)]
        all_translated, all_usage = [], []
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            futures = {executor.submit(translate_batch, client, report_date, list(b)): b for b in batches}
            for future in as_completed(futures):
                translated, usage_log = future.result()  # a real exception here stops the whole run - by design
                all_translated.extend(translated)
                all_usage.extend(usage_log)

        by_id = {t["id"]: t for t in all_translated}
        expected_ids = {r["id"] for r in sections}
        missing = expected_ids - set(by_id)
        if missing:
            raise RuntimeError(f"{report_date}: {len(missing)} section id(s) never completed: {sorted(missing)}")

        for r in sections:
            t = by_id[r["id"]]
            conn.execute(
                "UPDATE report_sections SET topic_label_de = ?, comparison_text_de = ? WHERE id = ?",
                (t["topic_label_de"], t["comparison_text_de"], r["id"]),
            )
        conn.commit()

        cost = cost_of(all_usage)
        elapsed = time.time() - t0
        grand_total_cost += cost
        grand_total_sections += len(sections)
        print(f"{report_date}: {len(sections)} sections, {len(batches)} batch(es) -> ${cost:.4f}  ({elapsed:.0f}s)")
        log["reports"][report_date] = {
            "sections": len(sections), "batches": len(batches),
            "cost_usd": round(cost, 4), "elapsed_s": round(elapsed, 1),
            "input_tokens": sum(u["input_tokens"] for u in all_usage),
            "output_tokens": sum(u["output_tokens"] for u in all_usage),
        }
        OUT_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")

    conn.close()
    print(f"\nDone: {grand_total_sections} section(s) backfilled this run, "
          f"total cost ${grand_total_cost:.4f}, {time.time() - t_start:.0f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="One-off backfill: German rewrite for existing report_sections.")
    parser.add_argument("--date", help="Limit to a single report_date (YYYY-MM-DD) for testing.")
    args = parser.parse_args()
    run(only_date=args.date)
