"""Stage 1 of Analysis: broad relevance screening with Claude Haiku.

Reads pages from extracted_pages that have not yet been screened, asks Haiku
a binary "might this page contain geopolitical opinion/commentary?" question,
and records the verdict plus a short reasoning in page_screening. Deliberately
a wide net - see SYSTEM_PROMPT. Independent of analyze.py (Stage 2), which
only reads pages this stage already marked is_relevant=1.
One-shot run - not a long-running daemon.
"""

import argparse
import hashlib
import sys
from datetime import datetime, timezone

import anthropic
from dotenv import load_dotenv

from src.common.db import (
    claim_report_date_on_first_scan,
    get_connection,
    get_unscreened_pages,
    init_db,
    insert_page_screening,
    record_api_usage,
)

# Windows defaults stdout to the cp1252 console codepage even when redirected
# to a file, which raises UnicodeEncodeError on any print() containing a
# character outside it (e.g. Balkan/Slavic names) - fatal mid-run otherwise.
sys.stdout.reconfigure(encoding="utf-8")

MODEL = "claude-haiku-4-5-20251001"

# Explicit per-request ceiling (the Anthropic SDK's own default is 10 minutes)
# - added 2026-10-10 after a real screen.py timeout (see PROJECT_LOG). The DB
# showed steady ~1.7s/page progress with no stalls anywhere, so a hang was
# ruled out that time, but nothing before this guarded against one: a single
# truly stuck request could have silently sat for up to 10 minutes before the
# SDK's own timeout fired (still caught by the bare except below, but far
# later than necessary for a call this small - max_tokens=300, one page of
# text). 60s is generous for this call's normal size.
API_CALL_TIMEOUT_SECONDS = 60.0

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


def screen_page(client: anthropic.Anthropic, raw_text: str, model: str = MODEL, ref: str | None = None) -> tuple[bool, str]:
    """`model` defaults to the production screening model (MODEL) - the parameter
    exists so a controlled experiment can swap this one call (e.g. comparing
    Haiku 4.5 vs. Haiku 5.5, 2026-10-10) without touching any other part of the
    pipeline. Not wired to any production behavior change unless --screen-model
    is passed explicitly - see run()'s argparse default.

    tool_choice is forced ({"type": "tool", ...}) for the production model -
    same as it always has been. Newer models in the "5.5" generation (Opus 5.5,
    Sonnet 5.5) are documented (see synthesize.py's group_articles_into_topics())
    to reject forced tool_choice with a 400 - if a future --screen-model turns
    out to need the same {"type": "auto"} + explicit-instruction workaround,
    that model-conditional branch belongs here, mirroring synthesize.py exactly."""
    response = client.with_options(timeout=API_CALL_TIMEOUT_SECONDS).messages.create(
        model=model,
        max_tokens=300,
        system=SYSTEM_PROMPT,
        tools=[SCREEN_TOOL],
        tool_choice={"type": "tool", "name": "record_screening"},
        messages=[{"role": "user", "content": raw_text}],
    )
    record_api_usage("screen", model, response.usage, ref=ref)
    tool_use = next(b for b in response.content if b.type == "tool_use")
    return bool(tool_use.input["is_relevant"]), tool_use.input["reasoning"]


def compute_file_hash(local_path: str) -> str | None:
    """SHA-256 of the file on disk, or None if it can't be read (moved, deleted,
    permissions) - duplicate detection just degrades to "screen normally" for
    that file in that case, never a hard failure."""
    try:
        digest = hashlib.sha256()
        with open(local_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def find_duplicate_canonicals(conn, file_ids: list[int]) -> dict[int, int]:
    """For `file_ids` (the files with at least one page pending screening in
    this run), returns {duplicate_file_id: canonical_file_id} for every
    SHA-256 collision found among them - the lowest file_id in each matching
    group (first downloaded) is treated as canonical.

    Added 2026-10-10 (PROJECT_LOG) after a real incident: the same Economist
    issue arrived under two different filenames one minute apart and was
    independently screened twice, end to end - confirmed byte-identical via
    SHA-256, and the 3rd documented occurrence of this exact pattern (open
    action items 24/38/39). Deliberately scoped to files already in THIS
    run's pending batch, not the whole historical archive - that's the
    pattern actually observed (both copies arrive close together and sit
    unscreened side by side), and hashing every file ever downloaded on every
    run would be an unbounded, ever-growing cost for a case that hasn't been
    seen."""
    if not file_ids:
        return {}
    placeholders = ",".join("?" * len(file_ids))
    rows = conn.execute(
        f"SELECT id, local_path FROM downloaded_files WHERE id IN ({placeholders})",
        file_ids,
    ).fetchall()

    hash_to_ids: dict[str, list[int]] = {}
    for row in rows:
        file_hash = compute_file_hash(row["local_path"])
        if file_hash is None:
            continue
        hash_to_ids.setdefault(file_hash, []).append(row["id"])

    duplicate_of: dict[int, int] = {}
    for ids in hash_to_ids.values():
        if len(ids) < 2:
            continue
        canonical = min(ids)
        for file_id in ids:
            if file_id != canonical:
                duplicate_of[file_id] = canonical
    return duplicate_of


# --- Page-level duplicate detection (PROJECT_LOG 4.113) ---------------------------------------------------
# The file-level SHA-256 check above misses a file that is the same issue but not the same bytes (Der Spiegel
# 30.10: 136 of 136 pages identical in extracted text, different file bytes), and it only looks inside the current
# batch. 16 such pairs exist in the archive (Economist x8, Spiegel x3, LA Times x3, FAZ, Guardian UK, USA Today),
# some across days (LA Times 16.10 / 17.10). So a page whose normalized text equals a page of the SAME newspaper that
# was already screened - anywhere in the archive - copies that page's verdict and is not queued for analysis again.
# Full match only; pages shorter than MIN_DUPLICATE_PAGE_CHARS never match (covers, ads, near-empty pages).
MIN_DUPLICATE_PAGE_CHARS = 200
SKIPPED_DUPLICATE = "skipped_duplicate"


def normalize_page_text(text: str | None) -> str:
    """Case-folded, whitespace-collapsed text - what two extractions of the same page must agree on."""
    return " ".join((text or "").casefold().split())


def page_text_hash(text: str | None) -> str:
    """SHA-256 of the normalized page text, or '' when the page is too short to compare."""
    normalized = normalize_page_text(text)
    if len(normalized) < MIN_DUPLICATE_PAGE_CHARS:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def ensure_text_hashes(conn, batch_size: int = 2000) -> int:
    """Fills extracted_pages.text_hash for pages that have none yet (the whole archive on the first run, only new
    pages after that). Returns how many were computed."""
    done = 0
    while True:
        rows = conn.execute(
            "SELECT id, raw_text FROM extracted_pages WHERE text_hash IS NULL LIMIT ?", (batch_size,)
        ).fetchall()
        if not rows:
            return done
        conn.executemany(
            "UPDATE extracted_pages SET text_hash = ? WHERE id = ?",
            [(page_text_hash(row["raw_text"]), row["id"]) for row in rows],
        )
        conn.commit()
        done += len(rows)


class PageTextIndex:
    """{text_hash: (file_id, page_number)} of already-screened pages, per newspaper, loaded lazily. The earliest page
    (lowest file_id, then page number) is the canonical one."""

    def __init__(self, conn) -> None:
        self.conn = conn
        self._by_newspaper: dict[str, dict[str, tuple[int, int]]] = {}

    def _load(self, newspaper: str) -> dict[str, tuple[int, int]]:
        index: dict[str, tuple[int, int]] = {}
        rows = self.conn.execute(
            """
            SELECT ep.text_hash, ep.file_id, ep.page_number
            FROM extracted_pages ep
            JOIN page_screening ps ON ps.file_id = ep.file_id AND ps.page_number = ep.page_number
            JOIN downloaded_files df ON df.id = ep.file_id
            WHERE df.newspaper = ? AND ep.text_hash IS NOT NULL AND ep.text_hash != ''
            ORDER BY ep.file_id, ep.page_number
            """,
            (newspaper,),
        ).fetchall()
        for row in rows:
            index.setdefault(row["text_hash"], (row["file_id"], row["page_number"]))
        return index

    def lookup(self, newspaper: str | None, text_hash: str) -> tuple[int, int] | None:
        if not newspaper or not text_hash:
            return None
        if newspaper not in self._by_newspaper:
            self._by_newspaper[newspaper] = self._load(newspaper)
        return self._by_newspaper[newspaper].get(text_hash)

    def add(self, newspaper: str | None, text_hash: str, file_id: int, page_number: int) -> None:
        """Registers a page screened in this run, so a later page of the same run can match it."""
        if newspaper and text_hash:
            self._by_newspaper.setdefault(newspaper, self._load(newspaper)).setdefault(text_hash, (file_id, page_number))


def run(file_name_contains: str | None = None, screen_model: str = MODEL) -> None:
    load_dotenv()

    conn = get_connection()
    init_db(conn)

    if screen_model != MODEL:
        print(f"  *** EXPERIMENT: screening running with model={screen_model} instead of the production default ({MODEL}) ***")

    pages = get_unscreened_pages(conn, file_name_contains=file_name_contains)
    client = anthropic.Anthropic()

    hashed = ensure_text_hashes(conn)
    if hashed:
        print(f"  page-text hashes computed for {hashed} page(s)")
    text_index = PageTextIndex(conn)
    file_ids = sorted({p["file_id"] for p in pages})
    newspaper_by_file = {
        row["id"]: row["newspaper"]
        for row in conn.execute(
            f"SELECT id, newspaper FROM downloaded_files WHERE id IN ({','.join('?' * len(file_ids))})", file_ids
        )
    } if file_ids else {}

    duplicate_of = find_duplicate_canonicals(conn, file_ids)
    for dup_id, canonical_id in duplicate_of.items():
        print(f"  duplicate detected: file_id={dup_id} is byte-identical (SHA-256) to file_id={canonical_id} "
              f"- will copy screening verdicts instead of re-screening its pages")

    scanned = 0
    relevant = 0
    duplicates = 0
    duplicates_relevant = 0
    claim_checked: set[int] = set()  # files already offered to claim_report_date_on_first_scan() this run

    for page in pages:
        canonical_id = duplicate_of.get(page["file_id"])
        newspaper = newspaper_by_file.get(page["file_id"])
        copied_verdict = None
        duplicate_label = None  # what this page duplicates, for the log
        text_hash = ""
        if canonical_id is not None:
            copied_verdict = conn.execute(
                "SELECT is_relevant FROM page_screening WHERE file_id = ? AND page_number = ?",
                (canonical_id, page["page_number"]),
            ).fetchone()
            if copied_verdict is not None:
                duplicate_label = f"file_id={canonical_id}"
                reasoning = (
                    f"Duplicate page - this file is byte-identical (SHA-256) to file_id={canonical_id}; "
                    "verdict copied from that file's screening, not independently re-screened."
                )
                model_used = f"none (skipped - duplicate of file_id={canonical_id})"
        if copied_verdict is None:
            text_hash = page_text_hash(page["raw_text"])
            match = text_index.lookup(newspaper, text_hash)
            if match is not None:
                copied_verdict = conn.execute(
                    "SELECT is_relevant FROM page_screening WHERE file_id = ? AND page_number = ?", match
                ).fetchone()
            if match is not None and copied_verdict is not None:
                duplicate_label = f"file_id={match[0]} page={match[1]}"
                reasoning = (
                    f"Duplicate page - its text is identical to file_id={match[0]} page {match[1]} "
                    f"({newspaper}); verdict copied from that page's screening, not independently re-screened."
                )
                model_used = f"none (skipped - duplicate text of file_id={match[0]} page {match[1]})"

        if copied_verdict is not None:
            is_relevant = bool(copied_verdict["is_relevant"])
        elif not page["raw_text"].strip():
            is_relevant, reasoning, model_used = (
                False,
                "Page has no extractable text (blank or image-only page).",
                "none (empty page, skipped)",
            )
        else:
            try:
                is_relevant, reasoning = screen_page(
                    client, page["raw_text"], model=screen_model, ref=f"{page['file_id']}:{page['page_number']}"
                )
                model_used = screen_model
            except Exception as exc:
                print(f"  failed: file_id={page['file_id']} page={page['page_number']} ({exc})")
                continue

        if page["file_id"] not in claim_checked:
            claim_checked.add(page["file_id"])
            shift = claim_report_date_on_first_scan(conn, page["file_id"])
            if shift:
                reason = shift["hold_reason"] or (
                    f"no reason recorded - not screened on its download day (downloaded "
                    f"{datetime.fromisoformat(shift['downloaded_at']).astimezone():%H:%M} local)"
                )
                print(f"  REPORT_DATE_SHIFT file_id={shift['file_id']} ({shift['newspaper']}, {shift['file_name']}): "
                      f"{shift['original']} -> {shift['new']} (first screening happens on {shift['new']}; {reason})")

        insert_page_screening(
            conn,
            page["file_id"],
            page["page_number"],
            is_relevant,
            reasoning,
            datetime.now(timezone.utc).isoformat(),
            model_used,
            # a relevant duplicate was already queued for analysis through the page it copies - never analyze it twice
            analysis_status=SKIPPED_DUPLICATE if copied_verdict is not None and is_relevant else "pending",
        )
        if copied_verdict is None:
            text_index.add(newspaper, text_hash, page["file_id"], page["page_number"])
        scanned += 1
        relevant += int(is_relevant)
        duplicates += int(copied_verdict is not None)
        duplicates_relevant += int(copied_verdict is not None and is_relevant)
        tag =f"DUPLICATE of {duplicate_label}, copied" if copied_verdict is not None else "relevant"
        print(f"  page {page['page_number']} (file {page['file_id']}): {tag}={is_relevant} - {reasoning}")

    conn.close()

    pct = (relevant / scanned * 100) if scanned else 0
    print(f"\nScreening: {scanned} page(s) scanned, {relevant} flagged relevant ({pct:.0f}%)")
    if duplicates:
        print(f"Duplicates: {duplicates} page(s) copied a verdict instead of being screened, "
              f"{duplicates_relevant} of them relevant - not queued for analysis again")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage 1: broad relevance screening with Claude Haiku.")
    parser.add_argument(
        "--file",
        dest="file_name_contains",
        help="Limit to pages whose file_name contains this substring (for testing on a sample).",
    )
    parser.add_argument(
        "--screen-model",
        default=MODEL,
        help=(
            f"Model for screening only. Defaults to the production model ({MODEL}), "
            "so omitting this flag changes nothing. For controlled experiments only - "
            "see PROJECT_LOG 2026-10-10."
        ),
    )
    args = parser.parse_args()
    run(file_name_contains=args.file_name_contains, screen_model=args.screen_model)
