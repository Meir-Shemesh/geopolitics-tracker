"""One-off, read-only content-verification step for newspaper-source candidates
found by scripts/discover_additional_sources.py.

Downloads a handful of specific messages (by message_id) from the same
@demagazinesharing channel to a SCRATCH directory outside the project
(never data/raw/, never tracker.db) - this is deliberately isolated from the
real ingestion pipeline (fetch.py) since these are unvetted candidates, not
production sources yet. Then runs the same two independent checks as
scripts/pdf_health_check.py (imported directly, not reimplemented) plus a
short extracted-text sample per file, for a human to read and judge "is this
a real, complete, readable issue" - this script does not make that judgment
itself.

Never touches src/ingestion/fetch.py, guess_newspaper(), or any other
production code - verification only, no implementation.

Usage: python -m scripts.verify_candidate_sources
(candidates + message_ids are defined in CANDIDATES below - edit directly,
this is a one-off tool, not a general-purpose CLI)
"""
import asyncio
import os
import sys
from pathlib import Path

import pdfplumber
from dotenv import load_dotenv
from telethon import TelegramClient

from scripts.pdf_health_check import check_pdf
from src.ingestion.fetch import CHANNEL, SESSION_PATH

sys.stdout.reconfigure(encoding="utf-8")

SCRATCH_DIR = (
    Path(r"C:\Users\meir\AppData\Local\Temp\claude\c--Users-meir-OneDrive-Documents-Claude-Projects-geopolitics-tracker"
         r"\6f67474e-3a92-46ba-8e31-bae5adfdaa25\scratchpad\candidate_sources")
)

# (candidate label, [message_id, ...]) - message_ids picked from the most
# recent entries in scripts/output/discover_additional_sources_raw.json for
# each source's main group, a couple of days apart to catch single-day flukes.
CANDIDATES = [
    ("Frankfurter Allgemeine Zeitung (FAZ)", [30541, 30595]),
    ("Neue Zürcher Zeitung (NZZ)", [30465, 30596]),
    ("The Globe and Mail", [30459, 30590]),
    ("Financial Times (UK edition)", [30483, 30574]),
    ("Handelsblatt", [30428, 30593]),
    ("Financial Times (EU edition)", [30485, 30576]),
]

SAMPLE_PAGES = 3  # pages of extracted text to show per file, for human review


async def download_candidates(client: TelegramClient, channel: str) -> list[dict]:
    entity = await client.get_entity(channel)
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    downloaded = []

    for label, message_ids in CANDIDATES:
        for message_id in message_ids:
            messages = await client.get_messages(entity, ids=[message_id])
            message = messages[0] if messages else None
            if message is None or message.document is None:
                print(f"  *** WARNING: message_id={message_id} ({label}) not found or has no document - skipping ***")
                continue
            file_name = None
            for attr in message.document.attributes:
                if hasattr(attr, "file_name"):
                    file_name = attr.file_name
                    break
            file_name = file_name or f"{message_id}.pdf"
            local_path = SCRATCH_DIR / f"{message_id}_{file_name}"
            print(f"  downloading: {label} / {file_name} (message_id={message_id})...", flush=True)
            # One bad file must not take the whole batch down with it (see
            # fetch.py's own per-message try/except for the same reasoning) -
            # a first run here (2026-10-12) crashed silently mid-download of
            # a ~37MB file (truncated to exactly 25.0 MiB, a clean buffer-
            # boundary cutoff - a transient connection drop, not a code bug)
            # and took out every file queued after it with no visible error.
            for attempt in (1, 2):
                try:
                    await client.download_media(message, file=str(local_path))
                    downloaded.append({"label": label, "message_id": message_id, "file_name": file_name, "local_path": local_path})
                    break
                except Exception as e:
                    print(f"  *** WARNING: download failed for {label} / {file_name} (attempt {attempt}/2): {e!r} ***", flush=True)
                    if attempt == 2:
                        print(f"  *** giving up on {label} / {file_name} - continuing with the rest ***", flush=True)

    return downloaded


def sample_text(path: Path, num_pages: int = SAMPLE_PAGES) -> str:
    try:
        with pdfplumber.open(str(path)) as pdf:
            chunks = []
            for page in pdf.pages[:num_pages]:
                text = (page.extract_text() or "").strip()
                chunks.append(text[:600])
            return "\n  ---\n".join(chunks)
    except Exception as e:
        return f"(could not extract sample text: {e!r})"


def main():
    load_dotenv()
    api_id = os.environ["TELEGRAM_API_ID"]
    api_hash = os.environ["TELEGRAM_API_HASH"]

    async def run():
        async with TelegramClient(str(SESSION_PATH), int(api_id), api_hash) as client:
            return await download_candidates(client, CHANNEL)

    downloaded = asyncio.run(run())

    print(f"\nDownloaded {len(downloaded)} file(s) to {SCRATCH_DIR}/\n")
    print("=" * 80)

    for entry in downloaded:
        health = check_pdf(entry["local_path"])
        verdict = "SUSPECT" if health["suspect"] else "ok"
        print(f"\n### {entry['label']} - {entry['file_name']} (message_id={entry['message_id']}) ###")
        print(f"  pdf_health_check verdict: {verdict}")
        if health["error"]:
            print(f"  error: {health['error']}")
        else:
            print(f"  pages: producer={health['producer']!r} creator={health['creator']!r}")
            print(f"  page0_text_len={health['page0_text_len']} page0_images={health['page0_images']} "
                  f"pdflib_signature={health['pdflib_signature']} text_image_signature={health['text_image_signature']}")
        with pdfplumber.open(str(entry["local_path"])) as pdf:
            print(f"  total pages in PDF: {len(pdf.pages)}")
        print(f"  --- first {SAMPLE_PAGES} pages, extracted text sample ---")
        print(f"  {sample_text(entry['local_path'])}")


if __name__ == "__main__":
    main()
