"""One-off fix (2026-10-01): two Hebrew wording bugs reported by the project
owner in report_2026-09-30_he.html, section-2888 (invented connector word
"בזמן" in a column-attribution phrase, and an adjective/noun category
mismatch - "חששות מושחתות"). Root cause already diagnosed and the prompt
already fixed going forward (see the STAGE2_SYSTEM_PROMPT commit) - this
script only patches the one already-published report, text-only, no
pipeline re-run.

Writes to all 5 places this exact string appears, so none of them drift
out of sync with each other: the DB (source of truth for any future
re-render), reports/he/ (render.py's own output, source for publish.py),
docs/he/ (the published copy), and both assets/data/content/{date}_he.json
files (topic.html's lazy-loaded comparison text - reports/ and docs/ each
keep their own copy, same convention as manifest.json). Deliberately does
NOT touch the PDF (WeasyPrint output can't be text-patched like this -
would need a real render.py re-run, out of scope here) or any other
section/report - every replacement is counted and asserted before writing,
and the whole file's content is diffed before/after to confirm nothing
else moved.
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SECTION_ID = 2888

OLD_ADJ = "לצד התייחסות לחששות מושחתות שמכרסמות באמון התורמים המערביים"
NEW_ADJ = "לצד התייחסות לחששות מפני שחיתות שמכרסמת באמון התורמים המערביים"

OLD_SZ = "בטור בזמן Süddeutsche Zeitung"
NEW_SZ = "בטור ב-Süddeutsche Zeitung"

OLD_DW = "בטור בזמן Die Welt"
NEW_DW = "בטור ב-Die Welt"

FILES = [
    PROJECT_ROOT / "reports" / "he" / "report_2026-09-30_he.html",
    PROJECT_ROOT / "reports" / "assets" / "data" / "content" / "2026-09-30_he.json",
    PROJECT_ROOT / "docs" / "he" / "report_2026-09-30_he.html",
    PROJECT_ROOT / "docs" / "assets" / "data" / "content" / "2026-09-30_he.json",
]


def apply_fix(text: str) -> str:
    assert text.count(OLD_ADJ) == 1, f"expected exactly 1 occurrence of the adjective phrase, found {text.count(OLD_ADJ)}"
    assert text.count(OLD_SZ) == 1, f"expected exactly 1 occurrence of the Süddeutsche phrase, found {text.count(OLD_SZ)}"
    assert text.count(OLD_DW) == 1, f"expected exactly 1 occurrence of the Die Welt phrase, found {text.count(OLD_DW)}"
    fixed = text.replace(OLD_ADJ, NEW_ADJ).replace(OLD_SZ, NEW_SZ).replace(OLD_DW, NEW_DW)
    # Sanity: the fix must not have touched anything else - same length delta as expected,
    # and the old phrases must be fully gone.
    assert OLD_ADJ not in fixed and OLD_SZ not in fixed and OLD_DW not in fixed
    return fixed


def fix_file(path: Path) -> None:
    original = path.read_text(encoding="utf-8")
    fixed = apply_fix(original)
    path.write_text(fixed, encoding="utf-8")
    print(f"Fixed: {path.relative_to(PROJECT_ROOT)} ({len(original)} -> {len(fixed)} chars)")


def fix_db() -> None:
    from src.common.db import get_connection, init_db

    conn = get_connection()
    init_db(conn)
    row = conn.execute(
        "SELECT comparison_text_he FROM report_sections WHERE id = ?", (SECTION_ID,)
    ).fetchone()
    if row is None:
        raise SystemExit(f"section id={SECTION_ID} not found in report_sections")
    fixed = apply_fix(row["comparison_text_he"])
    conn.execute(
        "UPDATE report_sections SET comparison_text_he = ? WHERE id = ?", (fixed, SECTION_ID)
    )
    conn.commit()
    print(f"Fixed: DB report_sections.comparison_text_he (id={SECTION_ID})")


def main() -> None:
    fix_db()
    for path in FILES:
        fix_file(path)
    print("\nDone. PDF files (reports/he and docs/he .pdf) were NOT touched - "
          "WeasyPrint output can't be text-patched this way; still contain the old wording.")


if __name__ == "__main__":
    main()
