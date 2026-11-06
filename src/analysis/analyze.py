"""Stage 2 of Analysis: deep article extraction with Claude Sonnet.

Reads only pages that screen.py (Stage 1) already flagged is_relevant=1 and
that have not yet been analyzed, identifies individual opinion/commentary
articles on each page (accounting for the magazine/grid layout's non-
contiguous text - see HANDOFF.md "בעיות ידועות"), and records one row per
article in the articles table. Independent of screen.py - only reads its
output. One-shot run - not a long-running daemon.
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from src.common import batch_runner
from src.common.db import (
    BATCH_STAGE_SUFFIX,
    close_api_batch,
    get_connection,
    get_open_api_batches,
    get_pages_pending_analysis,
    insert_api_batch,
    init_db,
    insert_article,
    insert_article_conflict_zones,
    insert_article_countries,
    print_usage_summary,
    record_api_usage,
    usage_marker,
    set_analysis_status,
)
from src.common.geo_taxonomy import CONFLICT_ZONE_LABELS, country_codes, country_list_prompt_text

# Windows defaults stdout to the cp1252 console codepage even when redirected
# to a file, which raises UnicodeEncodeError on any print() containing a
# character outside it (e.g. Balkan/Slavic names) - fatal mid-run otherwise.
sys.stdout.reconfigure(encoding="utf-8")

MODEL = "claude-sonnet-5"

NEWSPAPER_LANGUAGES = {
    "Guardian": "en",
    "Daily Telegraph": "en",
    "Süddeutsche Zeitung": "de",
    "Die Welt": "de",
}

SYSTEM_PROMPT = """You are a geopolitical content analyst for a news-monitoring pipeline. You will be shown the raw text extracted from one newspaper page that has already been flagged as likely containing geopolitical opinion/commentary content.

Important: the source PDF uses a magazine/grid layout, not simple text columns. The extracted text may interleave paragraphs from multiple unrelated articles that happen to sit in adjacent boxes on the same physical page - sentences from different stories can appear next to each other out of true reading order. Use topic, tone, and narrative continuity (not just text order) to determine where one article ends and another begins.

For every distinct piece of geopolitical opinion, analysis, commentary, or significant factual reporting (see the significance criteria below) you can identify on this page (there may be zero, one, or several), call record_articles with one entry per article containing:
- headline: the article's headline/title as it appears, or a short descriptive title you construct if none is clearly printed.
- author: the byline name if present, otherwise an empty string. Only fill this in if you are confident the name belongs to THIS article - if there is any doubt that a nearby name is actually leaked text from an adjacent box (a real risk given the grid layout), leave it as an empty string rather than guess. An empty author is far better than a wrong one.
- region_topic: the primary geopolitical region or topic the piece concerns (e.g. "Russia-Ukraine war", "US-China trade relations", "Middle East / Gaza").
- stance_summary: for an opinion/analysis piece, 1-2 sentences summarizing the author's central argument or position - the actual stance taken, not a neutral topic description. For a significant factual report with no argued position, instead summarize the key facts and outcome of the event itself in 1-2 sentences.
- key_excerpt: one short verbatim quotation (under 40 words) from the text that best represents the piece's core claim.
- country_codes: zero or more ISO country codes from this closed list that the article substantively concerns (not just a passing mention) - {country_list}. A piece about US-Iran policy should include both "US" and "IR". If no specific country from this list applies, leave empty.
- conflict_zones: zero or more of israel_palestine_conflict, iran_west_conflict, russia_ukraine_conflict - ONLY if the article substantively concerns that specific conflict. Most articles concern none of these; do not force a match.

A piece qualifies as "geopolitical" only if it concerns international relations, foreign policy, cross-border conflicts, diplomacy, sanctions, geopolitical economics, or a similar international/cross-border dimension. Exclude opinion pieces about purely domestic policy that have no such dimension, even if they are legitimate, substantive political commentary - for example, exclude an op-ed arguing about a domestic pension reform, or one about retail workers' wages and unionization, if neither has an international angle. Also exclude news-brief items and content unrelated to geopolitics (culture, sport, lifestyle, etc.). Factual reporting without an opinion angle is usually excluded too, UNLESS the event it describes is significant enough to warrant inclusion on its own merits (scope widened 2026-10-04, replacing the opinion-only exclusion decided 2026-09-25 - see PROJECT_LOG 4.75: two documented cases, the Washington Post's global-deportation investigation on 2026-09-22 and France's nationwide student-protest story on 2026-10-02/04, fell through the opinion-only rule despite being screened as geopolitically relevant). This significance test is a SECOND, independent gate that only ever applies to a piece that has ALREADY cleared the international/cross-border requirement above - it never substitutes for that requirement or loosens it. A purely domestic story stays excluded no matter how large-scale, government-involved, or crisis-framed it is. Treat a factual report as significant enough to include only when the text itself documents at least TWO of the following about the SAME event (not scattered across unrelated stories on the page):
(1) mass-scale impact - arrests, casualties, displacement, or active participants numbering in the hundreds or more, OR explicitly described as nationwide/affecting an entire country or region rather than a single location/incident;
(2) direct confrontation with a government - a stated threat against, or a response by, a national government, head of state, or state security/military apparatus - not merely local police handling routine, contained disorder;
(3) a concrete policy response - newly announced, enacted, or explicitly under formal consideration, described as a direct reaction to this event;
(4) explicit crisis framing - the reporting itself frames the event as a crisis, unprecedented, or the worst/largest of its kind within a stated period, attributing that framing to an official, institution, or named expert quoted in the text - not merely the journalist's own descriptive language.
A single-person human-interest story, a routine local incident, a market update, or an isolated, contained protest/arrest remains excluded even if it has some international flavor - this bar is about the scale/institutional dimension of the event, not its emotional weight. Likewise excluded regardless of scale (added 2026-10-04 after this exact failure mode was observed - see PROJECT_LOG 4.75/4.76): a purely domestic lawsuit or scandal (e.g. a university sexual-assault case and the resulting public outcry), a party's internal domestic-policy debate (e.g. a pension-reform fight at a party conference), or a dispute between domestic levels of government (e.g. a state legislature defying national policy) - none of these gain a foreign-policy/cross-border dimension merely by being large, government-involved, or described as a crisis. When uncertain whether two of the four are genuinely met, OR whether the underlying event has a genuine international dimension at all, exclude.

If nothing on the page qualifies, call record_articles with an empty articles list.

Enforcement of the geopolitical bar above (2026-09-25, PROJECT_LOG 4.56/4.57 - tested against 7 real cases where this was previously violated): if a piece does not meet it, do NOT include it in the articles list with a stance_summary explaining that it "is not applicable" or "is non-geopolitical" or similar - that is a contradiction (an excluded piece should never appear in your output at all). Catching yourself about to write a stance_summary that says a piece isn't geopolitical is itself the signal to leave that piece out of the articles list entirely, not to include it anyway with a caveat.""".format(country_list=country_list_prompt_text())

ANALYZE_TOOL = {
    "name": "record_articles",
    "description": "Record every distinct opinion/commentary article identified on this page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "articles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "headline": {"type": "string"},
                        "author": {"type": "string"},
                        "region_topic": {"type": "string"},
                        "stance_summary": {"type": "string"},
                        "key_excerpt": {"type": "string"},
                        "country_codes": {"type": "array", "items": {"type": "string", "enum": country_codes()}},
                        "conflict_zones": {
                            "type": "array",
                            "items": {"type": "string", "enum": list(CONFLICT_ZONE_LABELS.keys())},
                        },
                    },
                    "required": [
                        "headline",
                        "author",
                        "region_topic",
                        "stance_summary",
                        "key_excerpt",
                        "country_codes",
                        "conflict_zones",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["articles"],
        "additionalProperties": False,
    },
    "strict": True,
}


# Structural signature check (not content-based) for a Letters to the Editor
# page - confirmed present, in the first ~200 chars where the page's own
# running header/section label sits, in WSJ ("LETTERS TO THE EDITOR") and
# Süddeutsche Zeitung ("Leserbriefe"/"LESERBRIEFE") via a full-archive scan
# (2026-09-25, PROJECT_LOG 4.55/4.56). Die Welt showed no equivalent marker
# across several German synonyms tried in that scan - a known, undocumented
# gap, not assumed covered; is_letters_page() returns False for a Die Welt
# letters page, same as for any newspaper not in this list, and that page
# falls through to ordinary per-item judgment with no extra scrutiny.
LETTERS_PAGE_MARKERS = ("LETTERS TO THE EDITOR", "LESERBRIEFE", "Leserbriefe")


def is_letters_page(raw_text: str) -> bool:
    head = raw_text[:200]
    return any(m in head for m in LETTERS_PAGE_MARKERS)


_LETTERS_PAGE_NOTE = (
    "Note: this page has been structurally identified as a Letters to the Editor page. "
    "Most reader letters are personal opinions on domestic matters with no international "
    "dimension and should be excluded per the rules above - apply this scrutiny to each "
    "letter individually, not by excluding the whole page: a letter that substantively "
    "concerns international relations, foreign policy, sanctions, or a named cross-border "
    "conflict still qualifies and should be included normally.\n"
)

# Code-level safety net (2026-09-25, PROJECT_LOG 4.56/4.57) for the same
# instability the enforcement instruction above targets - confirmed non-
# deterministic across repeated calls on at least one dense, multi-item page
# during testing (the same page returned three different subsets of its
# content across three calls, one of them re-including a piece the model had
# excluded before). Anchored at the start of stance_summary (not a bare
# substring-anywhere check) because every real observed case took this exact
# shape - "Not applicable - ...", "N/A - this is...", "Not geopolitical -
# excluded.", "Not a geopolitical piece; excluded from analysis." - an
# anchored match is far less likely to misfire on a legitimate article whose
# stance_summary happens to discuss geopolitical relevance deeper in the
# text. Same generic-code-safety-net pattern as _looks_suspicious() in
# synthesize.py - a backstop for the prompt instruction, not a replacement
# for it.
_SELF_EXCLUSION_RE = re.compile(
    r"^(not applicable|n/a\b|not geopolitical|non-geopolitical|not a geopolitical)",
    re.IGNORECASE,
)


def filter_self_tagged_articles(articles: list[dict]) -> tuple[list[dict], list[dict]]:
    """Returns (kept, excluded). An article is excluded only when its own
    stance_summary opens by saying it isn't geopolitical/applicable - the
    model's own words, not a judgment call made here."""
    kept, excluded = [], []
    for a in articles:
        if _SELF_EXCLUSION_RE.match(a["stance_summary"].strip()):
            excluded.append(a)
        else:
            kept.append(a)
    return kept, excluded


def build_analyze_params(newspaper: str, raw_text: str, is_letters_page_: bool = False) -> dict:
    """The one definition of an analysis request: analyze_page() sends it as a regular call and the batch path
    (PROJECT_LOG 4.129) puts the very same dict into a batch request, so the only difference is the way it is run."""
    letters_note = _LETTERS_PAGE_NOTE if is_letters_page_ else ""
    return dict(
        model=MODEL,
        max_tokens=8192,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        # The system prompt and the tool schema are identical for every page of a run (~4,000 tokens,
        # measured 2026-10-20 = 44% of each call's input). The cache breakpoint on the system block
        # covers the tools before it too, so every page after the first reads that prefix at 10% of
        # the input price. The output is unaffected (PROJECT_LOG 4.107).
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        tools=[ANALYZE_TOOL],
        tool_choice={"type": "tool", "name": "record_articles"},
        messages=[{"role": "user", "content": f"Newspaper: {newspaper}\n{letters_note}Page text:\n\n{raw_text}"}],
    )


def analyze_page(client: anthropic.Anthropic, newspaper: str, raw_text: str, is_letters_page_: bool = False,
                 ref: str | None = None) -> list[dict]:
    response = client.messages.create(**build_analyze_params(newspaper, raw_text, is_letters_page_))
    record_api_usage("analyze", MODEL, response.usage, ref=ref)
    tool_use = next(b for b in response.content if b.type == "tool_use")
    return tool_use.input["articles"]


# --- Operator skip list (PROJECT_LOG 4.113) ------------------------------------------------------------------
# On 2026-10-30 two duplicate issues were already queued when the run was under way and nothing could stop their
# analysis: this stage loads its whole page list at start, and the process could not be killed from outside. One
# file_id per line in this file (blank lines and "#" comments allowed) makes the loop skip that file's pages. It is
# re-read whenever it changes, so adding a line takes effect on the very next page of a run already in progress.
# The pages stay 'pending' (nothing is rewritten): removing the line lets a later run analyze them.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKIP_FILES_PATH = PROJECT_ROOT / "automation_state" / "skip_files.txt"


def parse_skip_file_ids(text: str) -> tuple[set[int], list[str]]:
    """(file ids, unreadable lines). A line is `<id>` optionally followed by a `#` comment."""
    ids: set[int] = set()
    bad: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.isdigit():
            ids.add(int(line))
        else:
            bad.append(raw.strip())
    return ids, bad


class SkipList:
    """The skip-list file, re-read only when its modification time or size changes. A missing or unreadable file
    means "nothing to skip" (or the last good content) - it must never be able to stop or crash a run."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._stamp: tuple[int, int] | None = None
        self._ids: set[int] = set()

    def ids(self) -> set[int]:
        try:
            stat = self.path.stat()
        except OSError:
            self._stamp, self._ids = None, set()
            return self._ids
        stamp = (stat.st_mtime_ns, stat.st_size)
        if stamp != self._stamp:
            try:
                ids, bad = parse_skip_file_ids(self.path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                return self._ids
            self._stamp, self._ids = stamp, ids
            print(f"  skip list: {sorted(ids) if ids else 'empty'} ({self.path.name})")
            for line in bad:
                print(f"  skip list: ignoring unreadable line {line!r}")
        return self._ids


# --- Failed-page record (PROJECT_LOG 4.128) ----------------------------------------------------------------------
# A page whose analysis fails stays 'pending' and is retried by the next run; before this record the only trace was a
# "failed:" line in the middle of the stage's output, which the daily log's tail-only capture drops on a long run
# (6.11: "3 page(s) failed" with no way to tell which). RECORD ONLY: nothing here changes what is analyzed, retried
# or written to the database, and a failure to write the record never stops a run.
FAILED_PAGES_DIR = PROJECT_ROOT / "data" / "processed" / "review_flags"
FAILED_ERROR_MESSAGE_LIMIT = 160


def describe_failure(page, exc: BaseException) -> dict:
    """One failed page: where it is and what went wrong (exception class + a short message)."""
    message = " ".join(str(exc).split())
    return {
        "file_id": page["file_id"],
        "page_number": page["page_number"],
        "newspaper": page["newspaper"],
        "error_type": type(exc).__name__,
        "error": message[:FAILED_ERROR_MESSAGE_LIMIT],
    }


def format_failed_pages(failed: list[dict]) -> list[str]:
    """The lines printed under the stage summary - kept at the very end so the log's tail always carries them."""
    return [
        f"  failed page: file_id={f['file_id']} page={f['page_number']} ({f['newspaper']}) "
        f"{f['error_type']}: {f['error']}"
        for f in failed
    ]


def write_failed_pages_record(failed: list[dict], flag_dir: Path | None = None, now: datetime | None = None) -> Path | None:
    """Appends this run's failures to data/processed/review_flags/<local date>.analyze_failed.json (several runs on
    one day add entries; an unreadable earlier file is replaced). Nothing is written when no page failed.
    Returns the path, or None. Never raises."""
    if not failed:
        return None
    try:
        now = now or datetime.now().astimezone()
        flag_dir = flag_dir or FAILED_PAGES_DIR
        flag_dir.mkdir(parents=True, exist_ok=True)
        path = flag_dir / f"{now.date().isoformat()}.analyze_failed.json"
        runs: list = []
        if path.exists():
            try:
                previous = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(previous.get("runs"), list):
                    runs = previous["runs"]
            except (OSError, ValueError, AttributeError):
                runs = []
        runs.append({"at": now.isoformat(timespec="seconds"), "failed_pages": failed})
        path.write_text(json.dumps({"runs": runs}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return path
    except Exception as exc:  # noqa: BLE001 - recording must never stop a run
        print(f"  warning: could not write the failed-pages record ({exc}) - continuing.")
        return None


# --- Message Batches API (ANALYZE_USE_BATCH; PROJECT_LOG 4.129) ----------------------------------------------------
# Same request, same prompt, same model and parameters as analyze_page() (build_analyze_params() is the ONE definition
# of an analysis request) - sent as one batch (50% price) instead of one call per page. Everything after an answer
# comes back is the ordinary loop in run(): the same validation, the same one-transaction-per-page write, so there is
# ONE write path. A page without a usable batch result (the request errored/expired/was canceled/came back malformed,
# the batch timed out or could not be read) simply takes the regular analyze_page() call.
# Experiment 2026-11-06 (495 pages of 2026-11-06): 0 failures, 123 s for 395 pages, cache-hit rate 56.7% (production
# 56.4%), $2.28 instead of $4.62. Known difference: about 4.5% fewer country tags per article (PROJECT_LOG 4.129).
# Turn off: ANALYZE_USE_BATCH = False (commit), or run once with --no-batch.
ANALYZE_USE_BATCH = True
ANALYZE_BATCH_TIMEOUT_SECONDS = 20 * 60
ANALYZE_BATCH_POLL_SECONDS = 30.0
ANALYSIS_MODE_BATCH = "batch"
ANALYSIS_MODE_SYNC = "sync"
_CUSTOM_ID_RE = re.compile(r"^a-(\d+)-p(\d+)$")
_REQUIRED_ARTICLE_KEYS = {
    "headline", "author", "region_topic", "stance_summary",
    "key_excerpt", "country_codes", "conflict_zones",
}


def batch_custom_id(file_id: int, page_number: int) -> str:
    """Stable id of a page's request (<= 64 chars, [A-Za-z0-9_-] only, as the API requires)."""
    return f"a-{file_id}-p{page_number}"


def parse_custom_id(custom_id: str) -> tuple[int, int] | None:
    match = _CUSTOM_ID_RE.match(custom_id)
    return (int(match.group(1)), int(match.group(2))) if match else None


def validate_articles(articles) -> None:
    """The shape check applied to every page's answer, regular call or batch, before any DB write starts."""
    if not isinstance(articles, list):
        raise TypeError(f"expected a list of articles, got {type(articles).__name__}")
    for article in articles:
        if not isinstance(article, dict):
            raise TypeError(f"expected an article dict, got {type(article).__name__}")
        if not _REQUIRED_ARTICLE_KEYS.issubset(article):
            raise ValueError(f"article missing required key(s): {_REQUIRED_ARTICLE_KEYS - article.keys()}")


def _absorb_batch_results(results: dict, model: str, articles_by_page: dict) -> int:
    """Logs every billed result to api_usage (stage 'analyze_batch', priced at 50%) and keeps the answers that carry
    a list of articles (their contents are validated in run(), like a regular answer). Returns how many."""
    usable = 0
    for custom_id, result in results.items():
        key = parse_custom_id(custom_id)
        if result.usage is not None:  # succeeded requests are billed even if their content is unusable
            record_api_usage("analyze" + BATCH_STAGE_SUFFIX, model, result.usage,
                             ref=f"{key[0]}:{key[1]}" if key else custom_id)
        if key is None or not result.usable:
            continue
        articles = result.tool_input.get("articles")
        if not isinstance(articles, list):
            continue
        articles_by_page[key] = articles
        usable += 1
    return usable


def _finish_batch(conn, client, batch_id: str, request_ids: list[str], model: str, elapsed: float, timeout_seconds: float,
                  poll_seconds: float, sleep, monotonic, articles_by_page: dict, stats: dict) -> None:
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
    usable = _absorb_batch_results(results, model, articles_by_page)
    stats["usable"] += usable
    stats["returned"] += len(results)
    kinds: dict[str, int] = {}
    for result in results.values():
        kinds[result.kind] = kinds.get(result.kind, 0) + 1
    print(f"  [batch] {batch_id}: {note} - {len(results)} of {len(request_ids)} result(s) returned, {usable} usable "
          f"({', '.join(f'{k} {v}' for k, v in sorted(kinds.items())) or 'none'})")
    close_api_batch(conn, batch_id, "collected", note)


def run_batch_phase(conn, client, pages, skip_ids: set, model: str, timeout_seconds: float,
                    poll_seconds: float = batch_runner.DEFAULT_POLL_SECONDS,
                    sleep=time.sleep, monotonic=time.monotonic, now=None) -> tuple[dict, dict]:
    """Returns ({(file_id, page_number): [articles as returned]}, stats). Never raises for an API/network problem:
    whatever is missing from the result is analyzed by regular calls in run()'s loop.

    1. Batches a previous run left open (api_batches, status 'submitted' - the process died during the wait) are
       followed first and counted from THEIR creation time; their pages are not submitted again.
    2. The pages still needing the API go out as one batch (split only if a documented limit requires it); its id is
       stored the moment it is created. Pages of a skip-listed file are not sent."""
    stats = {"batches": 0, "requests": 0, "returned": 0, "usable": 0, "abandoned": 0, "resumed": 0, "wait_seconds": 0.0}
    articles_by_page: dict = {}
    attempted: set[str] = set()
    started = monotonic()
    now_utc = now or datetime.now(timezone.utc)
    try:
        for row in get_open_api_batches(conn, "analyze"):
            ids = json.loads(row["request_ids"])
            age = max(0.0, (now_utc - datetime.fromisoformat(row["created_at"])).total_seconds())
            print(f"  [batch] following {row['batch_id']} left open by an earlier run ({len(ids)} request(s), "
                  f"{age / 60:.0f} min old)")
            stats["resumed"] += 1
            attempted.update(ids)
            _finish_batch(conn, client, row["batch_id"], ids, model, age, timeout_seconds, poll_seconds, sleep, monotonic,
                          articles_by_page, stats)
        to_send = [p for p in pages
                   if p["file_id"] not in skip_ids
                   and (p["file_id"], p["page_number"]) not in articles_by_page
                   and batch_custom_id(p["file_id"], p["page_number"]) not in attempted]
        if to_send:
            requests = [{"custom_id": batch_custom_id(p["file_id"], p["page_number"]),
                         "params": build_analyze_params(p["newspaper"], p["raw_text"], is_letters_page(p["raw_text"]))}
                        for p in to_send]
            submitted = []
            for chunk in batch_runner.split_into_batches(requests):
                batch_id = batch_runner.create_batch(client, chunk)
                ids = [r["custom_id"] for r in chunk]
                insert_api_batch(conn, batch_id, "analyze", model, ids)  # committed before any waiting starts
                print(f"  [batch] submitted {batch_id}: {len(chunk)} request(s)")
                stats["batches"] += 1
                stats["requests"] += len(chunk)
                submitted.append((batch_id, ids, monotonic()))
            for batch_id, ids, created in submitted:
                _finish_batch(conn, client, batch_id, ids, model, monotonic() - created, timeout_seconds, poll_seconds,
                              sleep, monotonic, articles_by_page, stats)
    except Exception as exc:  # noqa: BLE001 - see docstring
        print(f"  [batch] batch phase failed ({type(exc).__name__}: {exc}) - remaining pages use regular calls")
    stats["wait_seconds"] = monotonic() - started
    return articles_by_page, stats


def run(file_id: int | None = None, use_batch: bool | None = None, batch_timeout_seconds: float | None = None) -> None:
    load_dotenv()

    conn = get_connection()
    init_db(conn)

    pages = get_pages_pending_analysis(conn, file_id=file_id)
    client = anthropic.Anthropic()

    pages_analyzed = 0
    pages_failed = 0
    failed_pages: list[dict] = []
    total_articles = 0
    total_self_excluded = 0

    skip_list = SkipList(SKIP_FILES_PATH)
    skipped_pages: dict[int, int] = {}

    batch_enabled = ANALYZE_USE_BATCH if use_batch is None else use_batch
    batch_articles: dict = {}
    batch_stats = None
    batch_pages = 0
    batch_fallback = 0
    if batch_enabled and pages:
        batch_articles, batch_stats = run_batch_phase(
            conn, client, pages, skip_list.ids(), MODEL,
            ANALYZE_BATCH_TIMEOUT_SECONDS if batch_timeout_seconds is None else batch_timeout_seconds,
            ANALYZE_BATCH_POLL_SECONDS,
        )

    for page in pages:
        if page["file_id"] in skip_list.ids():
            skipped_pages[page["file_id"]] = skipped_pages.get(page["file_id"], 0) + 1
            continue
        newspaper = page["newspaper"]
        language = NEWSPAPER_LANGUAGES.get(newspaper, "")
        letters_page = is_letters_page(page["raw_text"])

        from_batch = False
        try:
            articles = None
            batched = batch_articles.get((page["file_id"], page["page_number"]))
            if batched is not None:
                try:
                    validate_articles(batched)
                    articles, from_batch = batched, True
                except (TypeError, ValueError) as exc:
                    print(f"  batch answer for file_id={page['file_id']} page={page['page_number']} unusable ({exc}) "
                          f"- regular call")
            if articles is None:
                batch_fallback += int(batch_enabled)
                articles = analyze_page(
                    client, newspaper, page["raw_text"], is_letters_page_=letters_page,
                    ref=f"{page['file_id']}:{page['page_number']}",
                )
                validate_articles(articles)
        except Exception as exc:
            # Validate the whole response shape before any DB write starts (below) -
            # a page-level failure here must leave zero rows written, so a retry via
            # the pending-queue never risks inserting the same article twice.
            pages_failed += 1
            print(f"  failed: file_id={page['file_id']} page={page['page_number']} ({exc})")
            try:
                failed_pages.append(describe_failure(page, exc))
            except Exception:  # noqa: BLE001 - record-only
                pass
            continue

        articles, self_excluded = filter_self_tagged_articles(articles)
        for a in self_excluded:
            print(
                f"  auto-excluded (self-tagged non-geopolitical): file_id={page['file_id']} "
                f"page={page['page_number']} headline={a['headline']!r}"
            )
        total_self_excluded += len(self_excluded)

        now = datetime.now(timezone.utc).isoformat()
        # One transaction per page: the articles, their country/zone rows and the page's 'completed' status are
        # committed together, so a crash or kill in the middle leaves the page 'pending' with nothing half-written
        # (previously each insert committed on its own and a retry could insert the same article twice).
        try:
            for article in articles:
                article_id = insert_article(
                    conn,
                    page["file_id"],
                    page["page_number"],
                    newspaper,
                    language,
                    article["headline"],
                    article["author"],
                    article["region_topic"],
                    article["stance_summary"],
                    article["key_excerpt"],
                    now,
                    commit=False,
                )
                insert_article_countries(conn, article_id, article["country_codes"], commit=False)
                insert_article_conflict_zones(conn, article_id, article["conflict_zones"], commit=False)

            set_analysis_status(conn, page["file_id"], page["page_number"], "completed", commit=False,
                                mode=ANALYSIS_MODE_BATCH if from_batch else ANALYSIS_MODE_SYNC, analyzed_at=now)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        pages_analyzed += 1
        batch_pages += int(from_batch)
        total_articles += len(articles)
        print(f"  page {page['page_number']} (file {page['file_id']}): {len(articles)} article(s)"
              + (" [batch]" if from_batch else ""))

    conn.close()

    print(
        f"\nAnalysis: {pages_analyzed} page(s) analyzed, {pages_failed} page(s) failed, "
        f"{total_articles} article(s) identified in total, "
        f"{total_self_excluded} article(s) auto-excluded (self-tagged non-geopolitical)"
    )
    if batch_stats is not None:
        print(f"Batch: {batch_stats['batches']} submitted ({batch_stats['requests']} request(s)), "
              f"{batch_stats['resumed']} resumed, {batch_pages} page(s) from batch, {batch_fallback} regular-call "
              f"fallback(s), waited {batch_stats['wait_seconds']:.0f}s")
    if skipped_pages:
        print(
            f"Skipped by the skip list ({SKIP_FILES_PATH.name}): {sum(skipped_pages.values())} page(s) "
            f"of file_id(s) {sorted(skipped_pages)} - left 'pending'"
        )
    if failed_pages:
        print(f"Failed pages ({len(failed_pages)}) - left 'pending', retried by the next run:")
        for line in format_failed_pages(failed_pages):
            print(line)
        record = write_failed_pages_record(failed_pages)
        if record is not None:
            print(f"  recorded in {record.parent.name}/{record.name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage 2: deep article extraction with Claude Sonnet.")
    parser.add_argument(
        "--file-id",
        type=int,
        help="Limit to pages belonging to this downloaded_files.id (for testing on a sample).",
    )
    parser.add_argument(
        "--batch",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=f"Analyze with the Message Batches API (--batch) or with regular calls (--no-batch) for this run. "
             f"Default: ANALYZE_USE_BATCH = {ANALYZE_USE_BATCH}.",
    )
    parser.add_argument(
        "--batch-timeout-minutes",
        type=float,
        default=None,
        help=f"How long to wait for the batch before canceling it and falling back (default {ANALYZE_BATCH_TIMEOUT_SECONDS / 60:.0f}).",
    )
    args = parser.parse_args()
    started = usage_marker()
    try:
        run(
            file_id=args.file_id,
            use_batch=args.batch,
            batch_timeout_seconds=args.batch_timeout_minutes * 60 if args.batch_timeout_minutes else None,
        )
    finally:
        print_usage_summary("analyze", started, "analyze")
