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
import json
import re
import sys
import time
from datetime import datetime, timezone

import anthropic
from dotenv import load_dotenv

from src.common import batch_runner
from src.common.db import (
    BATCH_STAGE_SUFFIX,
    claim_report_date_on_first_scan,
    close_api_batch,
    get_connection,
    get_open_api_batches,
    get_unscreened_pages,
    init_db,
    insert_api_batch,
    insert_page_screening,
    print_usage_summary,
    record_api_usage,
    usage_marker,
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

# Message Batches API for the screening calls (50% price, asynchronous). OFF by default: with False nothing below the
# switch changes - same calls, same output, same dates. To turn on, set True here (commit), or run once with --batch.
# The wait is bounded: a batch still running after SCREEN_BATCH_TIMEOUT_SECONDS is canceled and its pages are screened
# with regular calls. daily_autorun's screen step allows 90 minutes, so wait + fallback calls must fit in that.
SCREEN_USE_BATCH = True
SCREEN_BATCH_TIMEOUT_SECONDS = 15 * 60
SCREEN_BATCH_POLL_SECONDS = 30.0

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


def build_screen_params(raw_text: str, model: str = MODEL) -> dict:
    """The one definition of a screening request - used by screen_page() and, unchanged, by the batch path."""
    return dict(
        model=model,
        max_tokens=300,
        system=SYSTEM_PROMPT,
        tools=[SCREEN_TOOL],
        tool_choice={"type": "tool", "name": "record_screening"},
        messages=[{"role": "user", "content": raw_text}],
    )


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
    response = client.with_options(timeout=API_CALL_TIMEOUT_SECONDS).messages.create(**build_screen_params(raw_text, model))
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


# Pages whose font glyphs were never mapped to characters come out of the extractor as "(cid:123)" tokens. A page with
# fewer than MIN_REAL_CHARS_AFTER_CID real characters once those tokens are removed has nothing the model could screen.
# Measured on a 58-page sample of the archive (PROJECT_LOG 4.132): every such page was an advertisement, a fashion/photo
# page, a TV listing or a section cover - none was an article. Marked not relevant without an API call, in the batch
# and the regular path alike, the same way an empty page is.
MIN_REAL_CHARS_AFTER_CID = 100
UNREADABLE_CID_REASONING = (
    f"unreadable (cid): fewer than {MIN_REAL_CHARS_AFTER_CID} real characters once (cid:N) glyph codes are removed "
    "- not screened by the model."
)
UNREADABLE_CID_MODEL = "none (unreadable cid, skipped)"
_CID_TOKEN_RE = re.compile(r"\(cid:\d+\)")


def real_char_count(text: str | None) -> int:
    """Characters left after removing (cid:N) tokens and collapsing whitespace."""
    return len(" ".join(_CID_TOKEN_RE.sub(" ", text or "").split()))


def is_unreadable_cid(text: str | None) -> bool:
    """True only when the page does contain (cid:N) tokens AND under MIN_REAL_CHARS_AFTER_CID real characters remain.
    A short page without any (cid:N) is not this case and still goes to the model."""
    return bool(text) and _CID_TOKEN_RE.search(text) is not None and real_char_count(text) < MIN_REAL_CHARS_AFTER_CID


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
            if newspaper not in self._by_newspaper:  # setdefault(..., self._load(...)) would reload on every page
                self._by_newspaper[newspaper] = self._load(newspaper)
            self._by_newspaper[newspaper].setdefault(text_hash, (file_id, page_number))


class ScreenTimings:
    """Splits the wall time of each page into API time (the request, including any SDK-internal retries, until the
    answer is back) and code time (everything else in the page's turn: text hashing, duplicate lookups, DB writes,
    printing). Added 2026-11-01 to tell a slow API/network from a regression in this module's own work, after the
    per-call interval went from ~2 s to 5-10 s from 2026-10-31 (PROJECT_LOG 4.113) with unchanged payloads."""

    def __init__(self) -> None:
        self.api: list[float] = []  # one entry per page that actually called the API
        self.code: list[float] = []  # one entry per page processed

    def add(self, api_seconds: float, code_seconds: float) -> None:
        self.code.append(code_seconds)
        if api_seconds > 0:
            self.api.append(api_seconds)

    @staticmethod
    def _stats(values: list[float], digits: int) -> str:
        ordered = sorted(values)
        p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
        return (f"{len(ordered)} x, total {sum(ordered):.{digits}f}s, mean {sum(ordered) / len(ordered):.{digits}f}s, "
                f"median {ordered[len(ordered) // 2]:.{digits}f}s, p95 {p95:.{digits}f}s, max {ordered[-1]:.{digits}f}s")

    def summary(self, setup_seconds: float) -> str:
        if not self.code:
            return f"Timing: no page processed (setup {setup_seconds:.1f}s)"
        api_part = self._stats(self.api, 2) if self.api else "no API calls"
        return f"Timing: setup {setup_seconds:.1f}s | API: {api_part} | code per page: {self._stats(self.code, 3)}"


# --- Message Batches API (SCREEN_USE_BATCH) ---------------------------------------------------------------------
# Same requests, same prompt, same model and parameters as screen_page() - sent as one batch (50% price) instead of one
# call per page. The decision which pages need the API is pages_needing_api(); everything after the answer comes back
# is the ordinary loop in run(), so there is ONE write path for verdicts. A page without a usable batch result (the
# request errored/expired/was canceled, the batch timed out or failed) simply takes the regular screen_page() call.
# Experiment 2026-11-05 (460 pages of 2026-11-01): finished in 145 s, 0 failures, 96.5% agreement with the stored verdicts.
_CUSTOM_ID_RE = re.compile(r"^s-(\d+)-p(\d+)$")


def batch_custom_id(file_id: int, page_number: int) -> str:
    """Stable id of a page's request (<= 64 chars, [A-Za-z0-9_-] only, as the API requires)."""
    return f"s-{file_id}-p{page_number}"


def parse_custom_id(custom_id: str) -> tuple[int, int] | None:
    match = _CUSTOM_ID_RE.match(custom_id)
    return (int(match.group(1)), int(match.group(2))) if match else None


def pages_needing_api(conn, pages, duplicate_of: dict[int, int], newspaper_by_file: dict) -> list:
    """The pages for which run() would call the API, decided with the same three rules the loop applies, in order:
    (1) a page of a byte-identical duplicate file whose canonical page has a verdict copies it; (2) a page whose
    normalized text equals an already-screened page of the same newspaper copies it; (3) a page with no text is
    recorded as empty. Everything else needs the API. Pages earlier in this run count as screened (they will have a
    verdict by the time a later page is reached); if one of them in fact fails, the later duplicate just takes a
    regular call in the loop - an under-count here costs nothing but the discount."""
    index = PageTextIndex(conn)
    processed: set[tuple[int, int]] = set()
    needed = []
    for page in pages:
        key = (page["file_id"], page["page_number"])
        canonical_id = duplicate_of.get(page["file_id"])
        copied = False
        if canonical_id is not None:
            canonical_key = (canonical_id, page["page_number"])
            copied = canonical_key in processed or conn.execute(
                "SELECT 1 FROM page_screening WHERE file_id = ? AND page_number = ?", canonical_key).fetchone() is not None
        if not copied:
            newspaper = newspaper_by_file.get(page["file_id"])
            text_hash = page_text_hash(page["raw_text"])
            copied = index.lookup(newspaper, text_hash) is not None
            if not copied:
                index.add(newspaper, text_hash, page["file_id"], page["page_number"])
                if page["raw_text"].strip() and not is_unreadable_cid(page["raw_text"]):
                    needed.append(page)
        processed.add(key)
    return needed


def _absorb_batch_results(results: dict, model: str, verdicts: dict) -> int:
    """Logs every billed result to api_usage (stage 'screen_batch', priced at 50%) and keeps the usable verdicts.
    Returns how many were usable."""
    usable = 0
    for custom_id, result in results.items():
        key = parse_custom_id(custom_id)
        if result.usage is not None:  # succeeded requests are billed even if their content is unusable
            record_api_usage("screen" + BATCH_STAGE_SUFFIX, model, result.usage,
                             ref=f"{key[0]}:{key[1]}" if key else custom_id)
        if key is None or not result.usable:
            continue
        verdict = result.tool_input
        if not isinstance(verdict.get("is_relevant"), bool) or not isinstance(verdict.get("reasoning"), str):
            continue  # malformed answer: treated like a missing result, the loop asks again with a regular call
        verdicts[key] = (verdict["is_relevant"], verdict["reasoning"])
        usable += 1
    return usable


def _finish_batch(conn, client, batch_id: str, request_ids: list[str], model: str, elapsed: float, timeout_seconds: float,
                  poll_seconds: float, sleep, monotonic, verdicts: dict, stats: dict) -> None:
    """Waits for one batch (up to the shared timeout, counted from its creation), cancels it on timeout, collects what
    it produced and closes its api_batches row. A batch that cannot be read at all is abandoned: its pages fall back."""
    try:
        outcome = batch_runner.wait_for_batch(client, batch_id, timeout_seconds, poll_seconds, already_elapsed=elapsed,
                                              sleep=sleep, monotonic=monotonic)
        note = "ended"
        if outcome == "timeout":
            print(f"  [batch] {batch_id}: not finished after {timeout_seconds / 60:.0f} min - canceling; pages without a "
                  f"result take regular calls")
            batch_runner.cancel_batch(client, batch_id, poll_seconds, sleep=sleep, monotonic=monotonic)
            note = "timeout, canceled"
        results = batch_runner.fetch_results(client, batch_id)
    except Exception as exc:  # noqa: BLE001 - the pages of a lost batch must not be lost: they fall back to regular calls
        print(f"  [batch] {batch_id}: could not be read ({type(exc).__name__}: {exc}) - abandoned, its pages fall back")
        try:
            batch_runner.cancel_batch(client, batch_id, poll_seconds, max_wait=0, sleep=sleep, monotonic=monotonic)
        except Exception:  # noqa: BLE001
            pass
        close_api_batch(conn, batch_id, "abandoned", f"{type(exc).__name__}: {exc}"[:300])
        stats["abandoned"] += 1
        return
    usable = _absorb_batch_results(results, model, verdicts)
    stats["usable"] += usable
    stats["returned"] += len(results)
    kinds = {}
    for result in results.values():
        kinds[result.kind] = kinds.get(result.kind, 0) + 1
    print(f"  [batch] {batch_id}: {note} - {len(results)} of {len(request_ids)} result(s) returned, {usable} usable "
          f"({', '.join(f'{k} {v}' for k, v in sorted(kinds.items())) or 'none'})")
    close_api_batch(conn, batch_id, "collected", note)


def run_batch_phase(conn, client, pages, duplicate_of: dict[int, int], newspaper_by_file: dict, model: str,
                    timeout_seconds: float, poll_seconds: float = batch_runner.DEFAULT_POLL_SECONDS,
                    sleep=time.sleep, monotonic=time.monotonic, now=None) -> tuple[dict, dict]:
    """Returns ({(file_id, page_number): (is_relevant, reasoning)}, stats). Never raises for an API/network problem:
    whatever is missing from the result is screened by regular calls in run()'s loop.

    1. Batches a previous run left open (api_batches, status 'submitted' - the process died during the wait) are
       followed first and counted from THEIR creation time; their pages are not submitted again.
    2. The pages still needing the API go out as one batch (split only if a documented limit requires it); its id is
       stored the moment it is created."""
    stats = {"batches": 0, "requests": 0, "returned": 0, "usable": 0, "abandoned": 0, "resumed": 0, "wait_seconds": 0.0}
    verdicts: dict = {}
    attempted: set[str] = set()
    started = monotonic()
    now_utc = now or datetime.now(timezone.utc)
    try:
        needed = pages_needing_api(conn, pages, duplicate_of, newspaper_by_file)
        for row in get_open_api_batches(conn, "screen"):
            ids = json.loads(row["request_ids"])
            age = max(0.0, (now_utc - datetime.fromisoformat(row["created_at"])).total_seconds())
            print(f"  [batch] following {row['batch_id']} left open by an earlier run ({len(ids)} request(s), "
                  f"{age / 60:.0f} min old)")
            stats["resumed"] += 1
            attempted.update(ids)
            _finish_batch(conn, client, row["batch_id"], ids, model, age, timeout_seconds, poll_seconds, sleep, monotonic,
                          verdicts, stats)
        to_send = [p for p in needed
                   if (p["file_id"], p["page_number"]) not in verdicts
                   and batch_custom_id(p["file_id"], p["page_number"]) not in attempted]
        if to_send:
            requests = [{"custom_id": batch_custom_id(p["file_id"], p["page_number"]),
                         "params": build_screen_params(p["raw_text"], model)} for p in to_send]
            submitted = []
            for chunk in batch_runner.split_into_batches(requests):
                batch_id = batch_runner.create_batch(client, chunk)
                ids = [r["custom_id"] for r in chunk]
                insert_api_batch(conn, batch_id, "screen", model, ids)  # committed before any waiting starts
                print(f"  [batch] submitted {batch_id}: {len(chunk)} request(s)")
                stats["batches"] += 1
                stats["requests"] += len(chunk)
                submitted.append((batch_id, ids, monotonic()))
            for batch_id, ids, created in submitted:
                _finish_batch(conn, client, batch_id, ids, model, monotonic() - created, timeout_seconds, poll_seconds,
                              sleep, monotonic, verdicts, stats)
    except Exception as exc:  # noqa: BLE001 - see docstring
        print(f"  [batch] batch phase failed ({type(exc).__name__}: {exc}) - remaining pages use regular calls")
    stats["wait_seconds"] = monotonic() - started
    return verdicts, stats


def run(file_name_contains: str | None = None, screen_model: str = MODEL, use_batch: bool | None = None,
        batch_timeout_seconds: float | None = None) -> None:
    load_dotenv()
    # The processing day is fixed here, at the start of the run. In batch mode the verdicts are written after a wait of
    # minutes to hours (possibly past midnight), and claim_report_date_on_first_scan() must not see that later moment.
    run_started_iso = datetime.now(timezone.utc).isoformat()
    batch_enabled = SCREEN_USE_BATCH if use_batch is None else use_batch
    setup_started = time.perf_counter()
    timings = ScreenTimings()

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
    setup_seconds = time.perf_counter() - setup_started

    batch_verdicts: dict = {}
    batch_stats = None
    if batch_enabled:
        batch_verdicts, batch_stats = run_batch_phase(
            conn, client, pages, duplicate_of, newspaper_by_file, screen_model,
            SCREEN_BATCH_TIMEOUT_SECONDS if batch_timeout_seconds is None else batch_timeout_seconds,
            SCREEN_BATCH_POLL_SECONDS,
        )
    batch_used = 0
    batch_fallback = 0

    for page in pages:
        page_started = time.perf_counter()
        api_seconds = 0.0
        from_batch = False
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
        elif is_unreadable_cid(page["raw_text"]):
            is_relevant, reasoning, model_used = False, UNREADABLE_CID_REASONING, UNREADABLE_CID_MODEL
        else:
            api_started = time.perf_counter()
            try:
                batched = batch_verdicts.get((page["file_id"], page["page_number"]))
                if batched is not None:
                    is_relevant, reasoning = batched
                    from_batch = True
                    batch_used += 1
                else:
                    batch_fallback += int(batch_enabled)
                    is_relevant, reasoning = screen_page(
                        client, page["raw_text"], model=screen_model, ref=f"{page['file_id']}:{page['page_number']}"
                    )
                model_used = screen_model
            except Exception as exc:
                api_seconds = time.perf_counter() - api_started
                timings.add(api_seconds, time.perf_counter() - page_started - api_seconds)
                print(f"  failed: file_id={page['file_id']} page={page['page_number']} after {api_seconds:.2f}s ({exc})")
                continue
            api_seconds = time.perf_counter() - api_started

        if page["file_id"] not in claim_checked:
            claim_checked.add(page["file_id"])
            shift = claim_report_date_on_first_scan(
                conn, page["file_id"], **({"now": run_started_iso} if batch_enabled else {}))
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
        code_seconds = time.perf_counter() - page_started - api_seconds
        timings.add(api_seconds, code_seconds)
        tag =f"DUPLICATE of {duplicate_label}, copied" if copied_verdict is not None else "relevant"
        print(f"  page {page['page_number']} (file {page['file_id']}): {tag}={is_relevant} "
              f"[{'batch' if from_batch else f'api {api_seconds:.2f}s'}, code {code_seconds:.3f}s] - {reasoning}")

    conn.close()

    pct = (relevant / scanned * 100) if scanned else 0
    print(f"\nScreening: {scanned} page(s) scanned, {relevant} flagged relevant ({pct:.0f}%)")
    batch_note = ""
    if batch_stats is not None:
        batch_note = (f" | batch: {batch_stats['batches']} submitted ({batch_stats['requests']} request(s)), "
                      f"{batch_stats['resumed']} resumed, {batch_used} page(s) from batch, {batch_fallback} regular-call "
                      f"fallback(s), waited {batch_stats['wait_seconds']:.0f}s")
    print(timings.summary(setup_seconds) + batch_note)
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
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Screen with the Message Batches API for this run (same as SCREEN_USE_BATCH = True).",
    )
    parser.add_argument(
        "--batch-timeout-minutes",
        type=float,
        default=None,
        help=f"How long to wait for the batch before canceling it and falling back (default {SCREEN_BATCH_TIMEOUT_SECONDS / 60:.0f}).",
    )
    args = parser.parse_args()
    started = usage_marker()
    try:
        run(
            file_name_contains=args.file_name_contains,
            screen_model=args.screen_model,
            use_batch=True if args.batch else None,
            batch_timeout_seconds=args.batch_timeout_minutes * 60 if args.batch_timeout_minutes else None,
        )
    finally:
        print_usage_summary("screen", started, "screen")
