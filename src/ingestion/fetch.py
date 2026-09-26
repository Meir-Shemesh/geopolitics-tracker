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
from telethon.errors import FloodWaitError
from telethon.tl.types import DocumentAttributeFilename

from src.common.db import get_connection, get_latest_published_at, init_db, is_downloaded, mark_downloaded

# Windows defaults stdout to the cp1252 console codepage even when redirected
# to a file, which raises UnicodeEncodeError on any print() containing a
# character outside it (e.g. Balkan/Slavic names) - fatal mid-run otherwise.
sys.stdout.reconfigure(encoding="utf-8")

CHANNEL = "demagazinesharing"
RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
SESSION_PATH = Path(__file__).resolve().parents[2] / "data" / "geopolitics_tracker"

MIN_SCAN_LIMIT = 200
MESSAGES_PER_DAY_MARGIN = 50


def compute_scan_limit(
    latest_published_at: str | None,
    now: datetime,
    per_day: int = MESSAGES_PER_DAY_MARGIN,
    minimum: int = MIN_SCAN_LIMIT,
) -> int:
    """Size the iter_messages() scan window to the actual gap since the last
    run, instead of a fixed constant - a multi-day gap accumulates enough
    channel traffic (~50 messages/day observed: 2-9 MVP sources plus a lot of
    non-MVP noise) that a fixed 200 can fail to reach back far enough to cover
    the oldest un-ingested day at all (confirmed in practice after a 6-day
    gap - see PROJECT_LOG). `minimum` keeps the normal one/two-day case at the
    original 200, since scaling down would risk under-scanning it.
    """
    if latest_published_at is None:
        return minimum
    days_since = (now - datetime.fromisoformat(latest_published_at)).days
    return max(minimum, days_since * per_day)


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
    # "suddeutsche" (umlaut simply dropped, not transliterated to "ue") is a
    # rare but real variant - seen once so far (2026-09-10, see PROJECT_LOG),
    # confirmed via full-history retroactive scan to be a one-off upload
    # quirk rather than a recurring naming convention. Kept as a permanent
    # pattern (not a one-time fix) since nothing rules out it recurring.
    if (
        "sueddeutsche" in normalized
        or "süddeutsche" in normalized
        or "suddeutsche" in normalized
        or re.search(r"\bsz\b", normalized)
    ):
        return "Süddeutsche Zeitung"
    if "welt" in normalized and "sonntag" not in normalized:
        return "Die Welt"
    if re.search(r"\bnyt\b", normalized) or "new york times" in normalized:
        # NYT download is suspended for EVERY edition - not just International.
        # Tried switching to the home edition + magazine on 2026-09-12 (see
        # PROJECT_LOG 4.34/4.35): both "NYT 1309.pdf" (118 pages) and "NYT
        # Magazine 1309.pdf" (48 pages) were confirmed corrupted end-to-end by
        # direct content inspection (tradingref.com, ~14 chars + 1 image, on
        # every sampled page cover-to-back) - the exact same pattern already
        # seen 6/6 times on the International edition (action item 27). The
        # corruption is evidently a property of how this channel sources NYT
        # content generally, not specific to the International edition's
        # branding - a filename-based edition switch cannot route around it.
        # Re-enable only after someone finds a working, non-corrupted feed for
        # any NYT edition at the source.
        return None
    if "wall street journal" in normalized or re.search(r"\bwsj\b", normalized):
        return "Wall Street Journal"
    if "los angeles times" in normalized or re.search(r"\bla\s*times\b", normalized):
        # Must require "Los Angeles" (or "LA") explicitly - "The Times UK" also
        # contains "times" alone and must not match here.
        return "Los Angeles Times"
    if "usa today" in normalized:
        return "USA Today"
    if "washington post" in normalized:
        # Requiring the full two-word phrase avoids any collision with other
        # "post"-named papers (e.g. New York Post) should the channel ever
        # carry one - "post" alone would be too broad to match safely.
        return "Washington Post"
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


# Sources temporarily suspended from download pending investigation - distinct
# in kind from a permanent dead-source exclusion baked directly into
# guess_newspaper() above (NYT): guess_newspaper() still correctly identifies
# a suspended source as itself (it isn't "not an MVP source"), this set is
# checked separately in fetch_channel(), and the expectation is this set goes
# back to empty once the root cause is understood or resolved - not that an
# entry stays here indefinitely. See PROJECT_LOG 4.59/4.60 for the
# investigation each entry is tracking.
SUSPENDED_SOURCES: set[str] = {
    # Added 2026-09-26: tradingref.com-family corruption 3 days running
    # (23.9 id=225, 24.9 id=235, 25.9 id=246 - two different defect shapes,
    # same problem family - see PROJECT_LOG 4.59/4.60), all excluded from
    # Screening by hand each day rather than caught before download. This is
    # a suspension-for-investigation, not a conclusion that the source itself
    # is unsustainable like NYT (whose failure was structural - image-only
    # end to end, confirmed across two different editions). Remove this entry
    # once the corruption's root cause is understood or resolved, whichever
    # comes first - not once WSJ "just happens" to come back clean one day
    # (25.9's WSJ file that DID come back clean was the Weekend edition, a
    # different product from the daily one that's actually been failing).
    "Wall Street Journal",
}


async def fetch_channel(client: TelegramClient, channel: str, conn, limit: int = 200) -> dict:
    print(f"  connecting to {channel}...", flush=True)
    entity = await client.get_entity(channel)
    print(f"  connected, scanning up to {limit} messages...", flush=True)
    channel_dir = RAW_DIR / channel

    found = 0
    skipped_not_mvp = 0
    skipped_existing = 0
    skipped_suspended = 0
    skipped_download_failed = 0
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
        if newspaper in SUSPENDED_SOURCES:
            skipped_suspended += 1
            continue

        if is_downloaded(conn, channel, message.id):
            skipped_existing += 1
            continue

        channel_dir.mkdir(parents=True, exist_ok=True)
        local_path = channel_dir / file_name
        # Printed *before* the download starts, not after - if download_media()
        # stalls (network stall, machine sleep, or a flood-wait above Telethon's
        # default 60s auto-sleep threshold that gets raised to us instead of
        # handled silently), this line is the last thing in the log and names
        # exactly which file it's stuck on, instead of a silent multi-hour gap
        # with no indication of where. See PROJECT_LOG for the incident this
        # was added after - a run whose per-file gaps grew from ~90s to an
        # unexplained ~3-hour one with nothing printed in between.
        print(f"  downloading: {file_name}...", flush=True)
        download_start = datetime.now(timezone.utc)
        download_failed = False
        while True:
            try:
                await client.download_media(message, file=str(local_path))
                break
            except FloodWaitError as e:
                print(f"  flood-wait: Telegram asked us to sleep {e.seconds}s before retrying {file_name}", flush=True)
                await asyncio.sleep(e.seconds)
            except Exception as exc:
                # 2026-09-26: a message can be persistently undownloadable from
                # Telegram's own side (seen here: repeated internal-server
                # timeouts on one file, reproduced identically across two
                # separate whole-script runs - not a one-off network blip that
                # a bare retry would clear). Previously any non-FloodWaitError
                # exception here crashed fetch_channel() entirely, silently
                # losing every other message still left to scan that run. Skip
                # just this one message instead - is_downloaded() stays False
                # for it, so it's retried fresh (not silently abandoned) the
                # next time fetch.py runs, same as any other not-yet-downloaded
                # message.
                print(f"  *** WARNING: download failed for {file_name} ({exc}) - skipping this message, not the whole run ***", flush=True)
                skipped_download_failed += 1
                download_failed = True
                break
        if download_failed:
            continue
        download_seconds = (datetime.now(timezone.utc) - download_start).total_seconds()

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
        print(f"  downloaded: {file_name} ({newspaper}) [{download_seconds:.1f}s]", flush=True)

    return {
        "found": found,
        "skipped_not_mvp": skipped_not_mvp,
        "skipped_existing": skipped_existing,
        "skipped_suspended": skipped_suspended,
        "skipped_download_failed": skipped_download_failed,
        "downloaded": downloaded,
    }


async def run() -> None:
    load_dotenv()

    api_id = os.environ["TELEGRAM_API_ID"]
    api_hash = os.environ["TELEGRAM_API_HASH"]

    conn = get_connection()
    init_db(conn)

    limit = compute_scan_limit(get_latest_published_at(conn), datetime.now(timezone.utc))

    try:
        async with TelegramClient(str(SESSION_PATH), int(api_id), api_hash) as client:
            stats = await fetch_channel(client, CHANNEL, conn, limit=limit)
    finally:
        conn.close()

    print(
        f"\n{CHANNEL}: found {stats['found']} PDF(s), "
        f"skipped {stats['skipped_not_mvp']} (not an MVP source), "
        f"skipped {stats['skipped_existing']} (already downloaded), "
        f"skipped {stats['skipped_suspended']} (source suspended - see SUSPENDED_SOURCES), "
        f"skipped {stats['skipped_download_failed']} (download failed - will retry next run), "
        f"downloaded {stats['downloaded']} new"
    )


if __name__ == "__main__":
    asyncio.run(run())
