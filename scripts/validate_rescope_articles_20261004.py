"""One-off validation pass for the 2026-10-04 analyze.py scope-widening
retroactive resynthesis (2026-10-02/03/04, PROJECT_LOG 4.75/4.76).

Background: re-running analyze.py with the widened scope (significant
factual reporting, not just opinion/analysis) produced 230 net-new articles
across those 3 dates - far more than the 10-20 estimated, and a manual
sample found ~15-20% of the newly-added articles had NO genuine
international/cross-border dimension (the base gate was meant to stay
unchanged but the model sometimes let the new significance test override
it - see PROJECT_LOG 4.76 for the exact failures found: a UK party-
conference pension story, a Cornell campus lawsuit, a California-vs-federal
drilling dispute).

Rather than a full re-analyze (expensive - re-extracts from raw page text),
this does a cheap, targeted validation: one short Haiku 4.5 call per
NEWLY-ADDED article (not all 702), classifying the already-extracted
fields (headline/region_topic/stance_summary/key_excerpt) - no page
re-extraction. Any article judged to have no genuine international
dimension is deleted from `articles` (+ its article_countries/
article_conflict_zones rows) - the underlying page and its screen.py
verdict are left untouched, so a page that correctly had NO article
extracted stays that way; this only prunes the article list.

"New" here means: belongs to downloaded_files.id in 294-313 AND its
(file_id, page_number) pair had ZERO articles in the pre-rescope DB
snapshot (the backup taken immediately before analyze.py was re-run).
Matches exactly the same 225-article set reported to the user before this
script was approved.

Usage: python -m scripts.validate_rescope_articles_20261004 [--dry-run]
"""
import argparse
import sqlite3
import sys

import anthropic
from dotenv import load_dotenv

from src.common.db import get_connection, init_db

sys.stdout.reconfigure(encoding="utf-8")

MODEL = "claude-haiku-4-5-20251001"

FILE_IDS = list(range(294, 314))

BACKUP_DB_PATH = (
    r"C:\Users\meir\AppData\Local\Temp\claude\c--Users-meir-OneDrive-Documents-Claude-Projects-geopolitics-tracker"
    r"\6f67474e-3a92-46ba-8e31-bae5adfdaa25\scratchpad\pre-rescope-backup-2026-10-04\tracker_pre_rescope.db"
)

SYSTEM_PROMPT = """You are validating entries already extracted into a geopolitical news-monitoring database. You will be shown one article's source newspaper, headline, region/topic, stance summary, and key excerpt - not the original newspaper page.

This pipeline's established scope draws the line as follows (fixed 2026-10-04, PROJECT_LOG 4.76 - the first version of this prompt wrongly excluded a newspaper's own foreign-desk coverage of another country's domestic affairs, which has always been in scope - e.g. a pre-existing report section on Brazil's corruption scandal predates this entire rescope):
- KEEP when the article's subject is a DIFFERENT country than the source newspaper's own home country (UK: Guardian, Daily Telegraph; US: USA Today, Los Angeles Times, Washington Post; Germany: Süddeutsche Zeitung, Die Welt, Der Spiegel) - this is foreign-desk "world news" coverage of that country's affairs, in scope regardless of whether the story itself involves diplomacy or relations between states. Examples that KEEP: Brazil's finances or China's economic policy covered by any of these outlets; Morocco's new prime minister; a civil conflict in Ethiopia; a nationwide protest movement in France - all reported by a non-domestic newspaper.
- EXCLUDE only when the article's subject IS the source newspaper's own home country's internal affairs, with no international angle - e.g. a British paper's op-ed on British pension reform, a US paper's story about a US university lawsuit or US federal agency policy, a German paper's story about a German defense-procurement scandal.
- KEEP regardless of the above when the piece substantively concerns relations/diplomacy/conflict/sanctions/economics BETWEEN countries, even involving the source's own country.
- The Economist has no single home country; judge its pieces only by the general rule: does it substantively concern international relations, diplomacy, conflict, sanctions, or geopolitical economics, or report on another country's affairs as world coverage (rather than a purely domestic US/UK/German legal or constitutional technicality that happens to run in its country sections)?

Call record_validation with:
- has_international_dimension: true if the article should be KEPT per the rules above.
- reasoning: one short sentence citing which rule applied and why."""

VALIDATION_TOOL = {
    "name": "record_validation",
    "description": "Record whether this already-extracted article has a genuine international/cross-border dimension.",
    "input_schema": {
        "type": "object",
        "properties": {
            "has_international_dimension": {"type": "boolean"},
            "reasoning": {"type": "string"},
        },
        "required": ["has_international_dimension", "reasoning"],
        "additionalProperties": False,
    },
    "strict": True,
}


def get_newly_added_articles(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    bconn = sqlite3.connect(BACKUP_DB_PATH)
    bcur = bconn.execute(
        f"SELECT DISTINCT file_id, page_number FROM articles WHERE file_id IN ({','.join('?' * len(FILE_IDS))})",
        FILE_IDS,
    )
    had_before = {(r[0], r[1]) for r in bcur.fetchall()}
    bconn.close()

    cur = conn.execute(
        f"""SELECT id, file_id, page_number, newspaper, headline, region_topic, stance_summary, key_excerpt
            FROM articles WHERE file_id IN ({','.join('?' * len(FILE_IDS))})
            ORDER BY file_id, page_number, id""",
        FILE_IDS,
    )
    return [r for r in cur.fetchall() if (r["file_id"], r["page_number"]) not in had_before]


def get_articles_for_pages(conn: sqlite3.Connection, pages: list[tuple[int, int]]) -> list[sqlite3.Row]:
    """Round-2 recovery scoping (2026-10-04): validate every CURRENT article on an
    explicit (file_id, page_number) list - used after re-running analyze.py on
    exactly the pages a miscalibrated first validation pass wrongly emptied out
    (see PROJECT_LOG 4.76). Unlike get_newly_added_articles(), this doesn't diff
    against the pre-rescope backup - every article on these pages right now is
    freshly regenerated and needs (re-)validating."""
    out = []
    for fid, pg in pages:
        cur = conn.execute(
            """SELECT id, file_id, page_number, newspaper, headline, region_topic, stance_summary, key_excerpt
               FROM articles WHERE file_id = ? AND page_number = ? ORDER BY id""",
            (fid, pg),
        )
        out.extend(cur.fetchall())
    return out


def validate_article(client: anthropic.Anthropic, article: sqlite3.Row) -> tuple[bool, str]:
    content = (
        f"newspaper: {article['newspaper']}\n"
        f"headline: {article['headline']}\n"
        f"region_topic: {article['region_topic']}\n"
        f"stance_summary: {article['stance_summary']}\n"
        f"key_excerpt: {article['key_excerpt']}"
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=SYSTEM_PROMPT,
        tools=[VALIDATION_TOOL],
        tool_choice={"type": "tool", "name": "record_validation"},
        messages=[{"role": "user", "content": content}],
    )
    tool_use = next(b for b in response.content if b.type == "tool_use")
    return bool(tool_use.input["has_international_dimension"]), tool_use.input["reasoning"]


def run(dry_run: bool = False, pages_file: str | None = None) -> None:
    load_dotenv()
    conn = get_connection()
    init_db(conn)
    conn.row_factory = sqlite3.Row

    if pages_file:
        import json
        with open(pages_file, encoding="utf-8") as f:
            pages = [tuple(p) for p in json.load(f)]
        articles = get_articles_for_pages(conn, pages)
        print(f"Validating {len(articles)} article(s) on {len(pages)} explicit page(s) (dry_run={dry_run})...")
    else:
        articles = get_newly_added_articles(conn)
        print(f"Validating {len(articles)} newly-added article(s) (dry_run={dry_run})...")

    client = anthropic.Anthropic()
    kept = 0
    removed = []

    for a in articles:
        ok, reasoning = validate_article(client, a)
        if ok:
            kept += 1
        else:
            removed.append((a, reasoning))
            print(f"  REMOVE id={a['id']} file={a['file_id']} page={a['page_number']}: {a['headline']!r}")
            print(f"    reasoning: {reasoning}")
            if not dry_run:
                conn.execute("DELETE FROM article_countries WHERE article_id = ?", (a["id"],))
                conn.execute("DELETE FROM article_conflict_zones WHERE article_id = ?", (a["id"],))
                conn.execute("DELETE FROM articles WHERE id = ?", (a["id"],))

    if not dry_run:
        conn.commit()
    conn.close()

    print()
    print(f"Validation complete: {len(articles)} checked, {kept} kept, {len(removed)} removed.")
    if dry_run and removed:
        print("(dry run - nothing was actually deleted)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate newly-added articles from the 2026-10-04 analyze.py rescope.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be removed without deleting anything.")
    parser.add_argument(
        "--pages-file",
        help="Path to a JSON file of [file_id, page_number] pairs - validates every CURRENT "
        "article on exactly those pages instead of diffing against the pre-rescope backup "
        "(round-2 recovery scoping, see get_articles_for_pages()).",
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run, pages_file=args.pages_file)
