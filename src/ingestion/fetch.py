"""Fetch PDF attachments from the @demagazinesharing Telegram channel into data/raw/.

Requires TELEGRAM_API_ID and TELEGRAM_API_HASH to be set (see .env.example).
Only PDFs recognized as one of the ten MVP newspapers are downloaded; everything
else is skipped without ever fetching its bytes. Already-downloaded messages are
skipped via the tracking DB in db.py. One-shot run - not a long-running daemon.
"""

import asyncio
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.types import DocumentAttributeFilename

from src.common.db import get_connection, init_db, is_downloaded, mark_downloaded

# Windows defaults stdout to the cp1252 console codepage even when redirected
# to a file, which raises UnicodeEncodeError on any print() containing a
# character outside it (e.g. Balkan/Slavic names) - fatal mid-run otherwise.
sys.stdout.reconfigure(encoding="utf-8")

CHANNEL = "demagazinesharing"
RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
SESSION_PATH = Path(__file__).resolve().parents[2] / "data" / "geopolitics_tracker"


def _is_pdf(document) -> bool:
    return document is not None and document.mime_type == "application/pdf"


def _file_name(document, message_id: int) -> str:
    for attr in document.attributes:
        if isinstance(attr, DocumentAttributeFilename):
            return attr.file_name
    return f"{message_id}.pdf"


def guess_newspaper(file_name: str) -> str | None:
    """Identify one of the ten MVP newspapers from a file name, or None."""
    lowered = file_name.lower()
    # Collapse "_"/"-" to spaces before matching, so "usa_today"/"la-times"/
    # "wsj_2708" match the same as "usa today"/"la times"/"wsj 2708" - the
    # actual separator convention varies per source and isn't worth hardcoding.
    # The Economist's "TE-YYYY-MM-DD" check below is matched against the
    # original `lowered` instead, since it relies on literal hyphens.
    normalized = re.sub(r"[_-]+", " ", lowered)

    if "guardian" in normalized:
        return "Guardian"
    if "telegraph" in normalized:
        return "Daily Telegraph"
    if "sueddeutsche" in normalized or "süddeutsche" in normalized or re.search(r"\bsz\b", normalized):
        return "Süddeutsche Zeitung"
    if "welt" in normalized and "sonntag" not in normalized:
        return "Die Welt"
    if re.search(r"\bnyt\b", normalized) or "new york times" in normalized:
        # NYT International download is suspended (not just "not an MVP
        # source" - the channel carries the domestic US home edition too,
        # which was already excluded here regardless): every copy observed
        # so far (6/6, see PROJECT_LOG action item 27) turned out to be the
        # tradingref.com scan-corruption pattern (near-empty page 0, single
        # embedded image, no real text) - downloading it only to delete it
        # after Extraction/health-check wastes bandwidth and API cost for
        # content that never survives. Re-enable once someone investigates
        # the root cause at the source (a working non-corrupted copy, or an
        # alternate channel/source for the same content).
        return None
    if "wall street journal" in normalized or re.search(r"\bwsj\b", normalized):
        return "Wall Street Journal"
    if "los angeles times" in normalized or re.search(r"\bla\s*times\b", normalized):
        # Must require "Los Angeles" (or "LA") explicitly - "The Times UK" also
        # contains "times" alone and must not match here.
        return "Los Angeles Times"
    if "usa today" in normalized:
        return "USA Today"
    if "web" in normalized and (
        "economist" in normalized or re.match(r"te-\d{4}-\d{2}-\d{2}", lowered)
    ):
        # The channel also carries several regional Economist editions (UK, EU,
        # Asia Pacific, Middle East and Africa, plus an unlabelled "standard"
        # one) under the same "Economist"/"TE-YYYY-MM-DD" naming - confirmed by
        # content comparison (2026-08-29) to be either duplicates of each other
        # (same cover story, different export/OCR quality) or affected by the
        # tradingref.com scan-corruption pattern. The "Web Edition" is the one
        # comprehensive edition combining every region's section in a single
        # file, so only its name pattern ("... WEB..."/"...Web Edition...") is
        # matched here - the others are skipped at download time rather than
        # fetched and discarded afterward.
        return "Economist"
    if "spiegel" in normalized:
        return "Der Spiegel"
    return None


async def fetch_channel(client: TelegramClient, channel: str, conn, limit: int = 200) -> dict:
    print(f"  connecting to {channel}...", flush=True)
    entity = await client.get_entity(channel)
    print(f"  connected, scanning up to {limit} messages...", flush=True)
    channel_dir = RAW_DIR / channel

    found = 0
    skipped_not_mvp = 0
    skipped_existing = 0
    downloaded = 0
    scanned = 0

    async for message in client.iter_messages(entity, limit=limit):
        scanned += 1
        if scanned % 20 == 0:
            # TEMPORARY diagnostic: pinpoint where a stalled/slow run is stuck,
            # since this loop had gone silent for 5+ minutes with no visible
            # progress. Remove once the network-stall investigation is done.
            print(f"  ...scanned {scanned}/{limit} messages ({found} PDF(s) found so far)", flush=True)
        if not _is_pdf(message.document):
            continue
        found += 1

        file_name = _file_name(message.document, message.id)
        newspaper = guess_newspaper(file_name)
        if newspaper is None:
            skipped_not_mvp += 1
            continue

        if is_downloaded(conn, channel, message.id):
            skipped_existing += 1
            continue

        channel_dir.mkdir(parents=True, exist_ok=True)
        local_path = channel_dir / file_name
        await client.download_media(message, file=str(local_path))

        mark_downloaded(
            conn,
            channel,
            message.id,
            file_name,
            newspaper,
            message.date.astimezone(timezone.utc).isoformat(),
            datetime.now(timezone.utc).isoformat(),
            str(local_path),
        )
        downloaded += 1
        print(f"  downloaded: {file_name} ({newspaper})", flush=True)

    return {
        "found": found,
        "skipped_not_mvp": skipped_not_mvp,
        "skipped_existing": skipped_existing,
        "downloaded": downloaded,
    }


async def run() -> None:
    load_dotenv()

    api_id = os.environ["TELEGRAM_API_ID"]
    api_hash = os.environ["TELEGRAM_API_HASH"]

    conn = get_connection()
    init_db(conn)

    try:
        async with TelegramClient(str(SESSION_PATH), int(api_id), api_hash) as client:
            stats = await fetch_channel(client, CHANNEL, conn)
    finally:
        conn.close()

    print(
        f"\n{CHANNEL}: found {stats['found']} PDF(s), "
        f"skipped {stats['skipped_not_mvp']} (not an MVP source), "
        f"skipped {stats['skipped_existing']} (already downloaded), "
        f"downloaded {stats['downloaded']} new"
    )


if __name__ == "__main__":
    asyncio.run(run())
