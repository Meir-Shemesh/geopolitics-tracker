"""One-off (2026-09-25, PROJECT_LOG action item ~55): safe cleanup of the
duplicate downloaded_files rows that accumulated across several sessions -
id=30 (Guardian, 27.8), id=205 (Economist, 18/19.9), id=228 (Guardian, 23.9),
id=229 (USA Today, 23.9).

Same safety bar as scripts/delete_dup_200.py before it: for every row, this
re-verifies from scratch, does not assume the earlier narrative record is
still accurate:
  1. SHA-256 byte-identity against the row it duplicates.
  2. 100% of its articles (if any) are orphaned - not referenced by any
     report_section_articles row, i.e. never actually published. A row with
     ANY non-orphaned article is refused, not partially deleted.

A comprehensive fresh duplicate scan (this session) found TWO FURTHER
duplicate pairs beyond the ones tracked in PROJECT_LOG so far - id=41/70
(Economist, 29.8) and id=105/107 (Economist, 5.9) - where BOTH rows in each
pair have 100% of their articles already included in an already-published
report (29.8 and 5.9 respectively). Per the exact criterion above, neither
qualifies for deletion here (deleting either would break a live report by
removing rows report_section_articles still points at) - they are
deliberately NOT touched by this script. This most likely means those two
reports currently double-count the same Economist content twice; that is a
separate, more involved problem (would need re-synthesis of two old, stable,
already-published reports - a different class of decision per CLAUDE.md's
"reopening a stable archive" principle) and is left for a dedicated,
separately-approved pass, not folded into this cleanup.

Deletes, in dependency order, for each approved row: article_countries ->
article_conflict_zones -> articles -> page_screening -> extracted_pages ->
downloaded_files, then the two on-disk files (raw PDF + extracted .txt copy,
if present) - matching delete_dup_200.py's precedent exactly.
"""
import hashlib
import os
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
conn = sqlite3.connect(ROOT / "data/processed/tracker.db")
conn.row_factory = sqlite3.Row

# (row to delete, row it duplicates)
CANDIDATES = [
    (30, 26),
    (205, 191),
    (228, 226),
    (229, 227),
]


def verify_and_delete(dup_id: int, keep_id: int) -> bool:
    print(f"\n=== candidate: delete id={dup_id}, duplicate of id={keep_id} ===")
    dup = conn.execute("SELECT * FROM downloaded_files WHERE id=?", (dup_id,)).fetchone()
    keep = conn.execute("SELECT * FROM downloaded_files WHERE id=?", (keep_id,)).fetchone()
    if not dup or not keep:
        print("  ABORT - one of the two rows is missing.")
        return False

    h_dup = hashlib.sha256(Path(dup["local_path"]).read_bytes()).hexdigest()
    h_keep = hashlib.sha256(Path(keep["local_path"]).read_bytes()).hexdigest()
    print(f"  sha256 match: {h_dup == h_keep} ({dup['file_name']} vs {keep['file_name']})")
    if h_dup != h_keep:
        print("  ABORT - not byte-identical.")
        return False

    article_ids = [r["id"] for r in conn.execute("SELECT id FROM articles WHERE file_id=?", (dup_id,))]
    n_articles = len(article_ids)
    if n_articles:
        placeholders = ",".join("?" * n_articles)
        n_included = conn.execute(
            f"SELECT COUNT(DISTINCT article_id) FROM report_section_articles WHERE article_id IN ({placeholders})",
            article_ids,
        ).fetchone()[0]
        print(f"  articles: {n_articles} total, {n_included} referenced by a published report")
        if n_included > 0:
            print("  ABORT - at least one article is in a published report. Refusing to delete.")
            return False
    else:
        print("  articles: 0 (nothing to check)")

    n_screened = conn.execute("SELECT COUNT(*) FROM page_screening WHERE file_id=?", (dup_id,)).fetchone()[0]
    n_extracted = conn.execute("SELECT COUNT(*) FROM extracted_pages WHERE file_id=?", (dup_id,)).fetchone()[0]
    print(f"  page_screening rows: {n_screened}, extracted_pages rows: {n_extracted} - will be removed")

    if article_ids:
        placeholders = ",".join("?" * len(article_ids))
        cc = conn.execute(f"DELETE FROM article_countries WHERE article_id IN ({placeholders})", article_ids).rowcount
        cz = conn.execute(f"DELETE FROM article_conflict_zones WHERE article_id IN ({placeholders})", article_ids).rowcount
        print(f"  deleted {cc} article_countries row(s), {cz} article_conflict_zones row(s)")
    conn.execute("DELETE FROM articles WHERE file_id=?", (dup_id,))
    conn.execute("DELETE FROM page_screening WHERE file_id=?", (dup_id,))
    conn.execute("DELETE FROM extracted_pages WHERE file_id=?", (dup_id,))
    conn.execute("DELETE FROM downloaded_files WHERE id=?", (dup_id,))
    conn.commit()

    pdf = Path(dup["local_path"])
    txt = ROOT / "data/processed/extracted" / (Path(dup["file_name"]).stem + ".txt")
    if pdf.exists():
        os.remove(pdf)
        print(f"  removed on-disk PDF: {pdf.name}")
    if txt.exists():
        os.remove(txt)
        print(f"  removed on-disk extracted-text copy: {txt.name}")

    print(f"  DONE - id={dup_id} deleted ({n_articles} article(s), {n_screened} page_screening row(s), "
          f"{n_extracted} extracted_pages row(s)).")
    return True


def main():
    deleted = []
    for dup_id, keep_id in CANDIDATES:
        if verify_and_delete(dup_id, keep_id):
            deleted.append(dup_id)
    print(f"\n=== SUMMARY: deleted {len(deleted)} row(s): {deleted} ===")
    conn.close()


if __name__ == "__main__":
    main()
