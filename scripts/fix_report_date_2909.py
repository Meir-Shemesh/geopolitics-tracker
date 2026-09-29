"""One-off DB fix (2026-09-30) - same convention as fix_sources_included.py:
a direct UPDATE on already-known-wrong metadata, no API call, not expected to
run again.

fetch.py ran on 2026-09-30 shortly after local midnight to catch up on
2026-09-29 (which had no pipeline run at all the day before). All 8 files it
found downloaded with report_date=2026-09-30, per mark_downloaded()'s normal
rule (local wall-clock time at download, which had already crossed midnight -
downloaded_at shows ~21:27-21:46 UTC, i.e. ~00:27-00:46 local given the +3h
DST offset). This is the project's first real (not theoretical) instance of
the "download lands between 00:00-03:00 local" edge case CLAUDE.md already
flagged as previously 0/168 - see PROJECT_LOG.

7 of the 8 files are unambiguously 2026-09-29 editions by filename (either
"_2909" or "September 29, 2026"). The 8th, "USA Today Sports Weekly_3009.pdf"
(id 273), carries a "_3009" filename and is deliberately left untouched here -
not reassigned to either date - per explicit instruction not to touch 2026-09-30
yet in this session; it keeps whatever report_date mark_downloaded() already
gave it and will be dealt with whenever 2026-09-30 itself is processed.
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")

from src.common.db import get_connection

FILE_IDS = [272, 274, 275, 276, 277, 278, 279]  # excludes 273 (USA Today Sports Weekly_3009.pdf) - see docstring
TARGET_DATE = "2026-09-29"


def run() -> None:
    conn = get_connection()
    conn.executemany(
        "UPDATE downloaded_files SET report_date = ? WHERE id = ?",
        [(TARGET_DATE, file_id) for file_id in FILE_IDS],
    )
    conn.commit()
    print(f"Updated {len(FILE_IDS)} row(s) to report_date={TARGET_DATE}: {FILE_IDS}")
    rows = conn.execute(
        "SELECT id, file_name, report_date FROM downloaded_files WHERE id > 271 ORDER BY id"
    ).fetchall()
    for row in rows:
        print(dict(row))
    conn.close()


if __name__ == "__main__":
    run()
