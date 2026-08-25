"""Stage 1 of Analysis: broad relevance screening with Claude Haiku.

Reads pages from extracted_pages that have not yet been screened, asks Haiku
a binary "might this page contain geopolitical opinion/commentary?" question,
and records the verdict plus a short reasoning in page_screening. Deliberately
a wide net - see SYSTEM_PROMPT. Independent of analyze.py (Stage 2), which
only reads pages this stage already marked is_relevant=1.
One-shot run - not a long-running daemon.
"""

import argparse
from datetime import datetime, timezone

import anthropic
from dotenv import load_dotenv

from src.common.db import get_connection, get_unscreened_pages, init_db, insert_page_screening

MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """You are a broad relevance filter for a geopolitical news-monitoring pipeline. You will be shown the raw text extracted from one page of a newspaper PDF. Some pages contain opinion or analysis articles about geopolitics (international relations, foreign policy, conflicts, diplomacy, sanctions, geopolitical economics, etc.) - possibly mixed with unrelated content from adjacent article boxes, because the source layout is a magazine/grid page, not simple columns.

This is a deliberately WIDE screening net. Your job is only to flag pages that MIGHT contain such content - a later, more careful stage will do the real analysis. When in doubt, mark true. It is much worse to miss a relevant page (false negative) than to pass through an irrelevant one (false positive).

Call record_screening with:
- is_relevant: true if this page might contain any geopolitical opinion/commentary content, even partially or ambiguously. false only if you are confident the page contains none (e.g. sports scores, TV listings, crossword, pure advertising, celebrity gossip with no geopolitical angle).
- reasoning: one short sentence (under 30 words) explaining your decision - this will be reviewed later to calibrate the filter."""

SCREEN_TOOL = {
    "name": "record_screening",
    "description": "Record whether this page might contain relevant geopolitical commentary/opinion content.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_relevant": {"type": "boolean"},
            "reasoning": {"type": "string"},
        },
        "required": ["is_relevant", "reasoning"],
        "additionalProperties": False,
    },
    "strict": True,
}


def screen_page(client: anthropic.Anthropic, raw_text: str) -> tuple[bool, str]:
    response = client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=SYSTEM_PROMPT,
        tools=[SCREEN_TOOL],
        tool_choice={"type": "tool", "name": "record_screening"},
        messages=[{"role": "user", "content": raw_text}],
    )
    tool_use = next(b for b in response.content if b.type == "tool_use")
    return bool(tool_use.input["is_relevant"]), tool_use.input["reasoning"]


def run(file_name_contains: str | None = None) -> None:
    load_dotenv()

    conn = get_connection()
    init_db(conn)

    pages = get_unscreened_pages(conn, file_name_contains=file_name_contains)
    client = anthropic.Anthropic()

    scanned = 0
    relevant = 0

    for page in pages:
        if not page["raw_text"].strip():
            is_relevant, reasoning, model_used = (
                False,
                "Page has no extractable text (blank or image-only page).",
                "none (empty page, skipped)",
            )
        else:
            try:
                is_relevant, reasoning = screen_page(client, page["raw_text"])
                model_used = MODEL
            except Exception as exc:
                print(f"  failed: file_id={page['file_id']} page={page['page_number']} ({exc})")
                continue

        insert_page_screening(
            conn,
            page["file_id"],
            page["page_number"],
            is_relevant,
            reasoning,
            datetime.now(timezone.utc).isoformat(),
            model_used,
        )
        scanned += 1
        relevant += int(is_relevant)
        print(f"  page {page['page_number']} (file {page['file_id']}): relevant={is_relevant} - {reasoning}")

    conn.close()

    pct = (relevant / scanned * 100) if scanned else 0
    print(f"\nScreening: {scanned} page(s) scanned, {relevant} flagged relevant ({pct:.0f}%)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage 1: broad relevance screening with Claude Haiku.")
    parser.add_argument(
        "--file",
        dest="file_name_contains",
        help="Limit to pages whose file_name contains this substring (for testing on a sample).",
    )
    args = parser.parse_args()
    run(file_name_contains=args.file_name_contains)
