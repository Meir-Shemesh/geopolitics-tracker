"""One-off, read-only scan of the @demagazinesharing Telegram channel to find
newspaper PDFs that src/ingestion/fetch.py's guess_newspaper() does not
recognize - candidates for expanding the 10-source MVP list.

Deliberately separate from fetch.py (imports from it, never edits it) and
never downloads any PDF bytes - only message metadata (filename, date,
caption, document size). Does not touch tracker.db at all: this is a
Telegram-side discovery question ("what regularly-posted sources exist that
we don't recognize yet"), independent of what's already been downloaded.

Groups filenames by a normalized "base name" (digits/dates stripped) so that
e.g. "Le Monde_1012.pdf" and "Le Monde_1013.pdf" count as the same candidate
source instead of two unique ones - frequency is what distinguishes a
regularly-posted source from a one-off upload.

Usage: python -m scripts.discover_additional_sources [--days 90]
"""
import argparse
import asyncio
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from telethon import TelegramClient

from src.ingestion.fetch import CHANNEL, SESSION_PATH, _file_name, _is_pdf, guess_newspaper

sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_DAYS = 90

_MONTH_NAMES = (
    r"jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|"
    r"january|february|march|april|june|july|august|september|october|november|december|"
    r"januar|februar|m[aä]rz|mai|juni|juli|oktober|dezember"
)
_MONTH_RE = re.compile(rf"\b({_MONTH_NAMES})\b")


def normalize_for_grouping(file_name: str) -> str:
    """Collapses date/issue-number variation out of a filename so repeat
    uploads of the same source group together. Mirrors guess_newspaper()'s
    own "_"/"-"-to-space normalization, plus stripping digits/month names/
    punctuation that guess_newspaper() doesn't need (it matches fixed brand
    substrings instead, so a stray digit never breaks its match)."""
    lowered = file_name.rsplit(".", 1)[0].lower()
    normalized = re.sub(r"[_-]+", " ", lowered)
    normalized = _MONTH_RE.sub(" ", normalized)
    normalized = re.sub(r"\d+", " ", normalized)
    normalized = re.sub(r"[,.]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized or "(blank after normalization)"


async def scan_unrecognized(client: TelegramClient, channel: str, cutoff: datetime) -> tuple[dict, int, int]:
    """Telethon auto-sleeps through flood-waits under its default 60s
    threshold on its own - metadata-only iteration (no download_media calls)
    is light enough that a longer one is unlikely, so this deliberately
    doesn't replicate fetch.py's manual FloodWaitError retry loop. If one
    does happen, it surfaces as an exception and the run can just be
    restarted by hand (no DB/download state to lose or duplicate here)."""
    entity = await client.get_entity(channel)
    groups: dict[str, list[dict]] = defaultdict(list)
    scanned = 0
    pdf_count = 0

    async for message in client.iter_messages(entity, limit=None):
        scanned += 1
        if message.date < cutoff:
            break
        if scanned % 200 == 0:
            print(f"  ...scanned {scanned} messages (back to {message.date.date()}), "
                  f"{pdf_count} PDF(s), {len(groups)} unrecognized group(s) so far", flush=True)
        if not _is_pdf(message.document):
            continue
        pdf_count += 1
        file_name = _file_name(message.document, message.id)
        if guess_newspaper(file_name) is not None:
            continue  # already recognized by the current MVP matcher - not a candidate
        base = normalize_for_grouping(file_name)
        groups[base].append({
            "file_name": file_name,
            "date": message.date.astimezone(timezone.utc).isoformat(),
            "caption": (message.message or "").strip() or None,
            "size_bytes": message.document.size,
            "message_id": message.id,
        })

    return groups, scanned, pdf_count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS,
                         help=f"How many days of channel history to scan (default {DEFAULT_DAYS}).")
    args = parser.parse_args()

    load_dotenv()
    api_id = os.environ["TELEGRAM_API_ID"]
    api_hash = os.environ["TELEGRAM_API_HASH"]
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)

    async def run():
        async with TelegramClient(str(SESSION_PATH), int(api_id), api_hash) as client:
            print(f"Scanning {CHANNEL} back to {cutoff.date()} ({args.days} days), metadata-only (no downloads)...", flush=True)
            return await scan_unrecognized(client, CHANNEL, cutoff)

    groups, scanned, pdf_count = asyncio.run(run())

    ranked = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)

    print(f"\nScanned {scanned} message(s), {pdf_count} PDF(s) total, "
          f"{len(groups)} unrecognized candidate group(s) ({sum(len(v) for v in groups.values())} unrecognized PDFs).")

    recurring = [(k, v) for k, v in ranked if len(v) >= 2]
    one_off = [(k, v) for k, v in ranked if len(v) == 1]

    print(f"\n=== Recurring candidates (2+ appearances in {args.days} days) - {len(recurring)} group(s) ===")
    for base, items in recurring:
        items_sorted = sorted(items, key=lambda r: r["date"])
        first, last = items_sorted[0], items_sorted[-1]
        captions = {i["caption"] for i in items if i["caption"]}
        print(f"\n  \"{base}\" - {len(items)}x, first={first['date'][:10]} last={last['date'][:10]}")
        for example in items_sorted[:3]:
            print(f"    e.g. {example['file_name']} ({example['size_bytes']:,} bytes)")
        if captions:
            for c in list(captions)[:2]:
                print(f"    caption: {c[:150]!r}")

    print(f"\n=== One-off appearances (likely not worth pursuing) - {len(one_off)} group(s) ===")
    for base, items in one_off:
        print(f"  \"{base}\" - {items[0]['file_name']} ({items[0]['date'][:10]})")

    os.makedirs("scripts/output", exist_ok=True)
    out_path = "scripts/output/discover_additional_sources_raw.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"scanned": scanned, "pdf_count": pdf_count, "days": args.days,
                   "groups": {k: v for k, v in ranked}}, f, ensure_ascii=False, indent=2)
    print(f"\nFull raw data written to {out_path}")


if __name__ == "__main__":
    main()
