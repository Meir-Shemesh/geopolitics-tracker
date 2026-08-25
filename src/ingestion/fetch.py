"""Fetch PDF attachments from the @demagazinesharing Telegram channel into data/raw/.

Requires TELEGRAM_API_ID and TELEGRAM_API_HASH to be set (see .env.example).
Only PDFs recognized as one of the four MVP newspapers are downloaded; everything
else is skipped without ever fetching its bytes. Already-downloaded messages are
skipped via the tracking DB in db.py. One-shot run - not a long-running daemon.
"""

import asyncio
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.types import DocumentAttributeFilename

from src.common.db import get_connection, init_db, is_downloaded, mark_downloaded

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
    """Identify one of the four MVP newspapers from a file name, or None."""
    lowered = file_name.lower()

    if "guardian" in lowered:
        return "Guardian"
    if "telegraph" in lowered:
        return "Daily Telegraph"
    if "sueddeutsche" in lowered or "süddeutsche" in lowered or re.search(r"\bsz\b", lowered):
        return "Süddeutsche Zeitung"
    if "welt" in lowered and "sonntag" not in lowered:
        return "Die Welt"
    return None


async def fetch_channel(client: TelegramClient, channel: str, conn, limit: int = 200) -> dict:
    entity = await client.get_entity(channel)
    channel_dir = RAW_DIR / channel

    found = 0
    skipped_not_mvp = 0
    skipped_existing = 0
    downloaded = 0

    async for message in client.iter_messages(entity, limit=limit):
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
        print(f"  downloaded: {file_name} ({newspaper})")

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
