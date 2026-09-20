"""One-off backfill: set downloaded_files.report_date for the files behind the orphaned articles.

The 2026-09-20 review found 308 articles (9.7% of the archive) that were analyzed but never
reached any report, because they were attached to a report day by published_at (the Telegram
upload time) and that day's report had already been built before they were analyzed
(PROJECT_LOG 4.43). The permanent rule - report day = local day of the actual download - only
applies to files ingested after it was introduced (report_date stays NULL for older rows).
This script applies the same rule retroactively, and only to the 20 files that hold those
articles: report_date = report_date_for_download(downloaded_at), the exact function
mark_downloaded() uses. It changes no report, calls no API and touches no other row - the
affected report dates still have to be rebuilt separately (synthesize --force).

Idempotent: rows that already have a report_date are left as they are.
"""

import sys

from src.common.db import get_connection, init_db, report_date_for_download

sys.stdout.reconfigure(encoding="utf-8")

# file id -> what it is. Ids come from the 2026-09-20 orphan review (articles never in a report).
ORPHAN_FILES = {
    # LA Times / WSJ / USA Today / NYT International, nominal 24-27.8, downloaded 28.8
    43: "24-27.8 batch", 44: "24-27.8 batch", 45: "24-27.8 batch", 47: "24-27.8 batch",
    48: "24-27.8 batch", 51: "24-27.8 batch", 52: "24-27.8 batch", 53: "24-27.8 batch",
    54: "24-27.8 batch", 55: "24-27.8 batch", 56: "24-27.8 batch", 57: "24-27.8 batch",
    # Washington Post, nominal 6-11.9, downloaded 13.9
    140: "WaPo 6-11.9", 141: "WaPo 6-11.9", 142: "WaPo 6-11.9", 143: "WaPo 6-11.9", 144: "WaPo 6-11.9",
    # Economist TE-2026-09-19, uploaded 17.9 (UTC), downloaded 18.9
    191: "Economist 19.9 issue",
    # Guardian UK 18.9 (2 articles from a page retried on 19.9) and WSJ Magazine (uploaded 18.9)
    187: "Guardian 18.9 (late page)", 199: "WSJ Magazine",
}


def run() -> None:
    conn = get_connection()
    init_db(conn)  # adds the report_date column if the DB predates it

    updated = 0
    for file_id, label in sorted(ORPHAN_FILES.items()):
        row = conn.execute(
            "SELECT id, newspaper, file_name, published_at, downloaded_at, report_date "
            "FROM downloaded_files WHERE id = ?",
            (file_id,),
        ).fetchone()
        if row is None:
            raise SystemExit(f"file id {file_id} ({label}) is not in downloaded_files - aborting, nothing written")

        new_date = report_date_for_download(row["downloaded_at"])
        legacy_date = row["published_at"][:10]
        if row["report_date"] is not None:
            print(f"  file {file_id:3d} {label:26s} already has report_date={row['report_date']} - skipped")
            continue

        conn.execute("UPDATE downloaded_files SET report_date = ? WHERE id = ?", (new_date, file_id))
        updated += 1
        print(f"  file {file_id:3d} {label:26s} {row['newspaper'][:22]:22s} published {legacy_date} -> report_date {new_date}")

    conn.commit()
    conn.close()
    print(f"\nDone: {updated} of {len(ORPHAN_FILES)} file(s) updated.")


if __name__ == "__main__":
    run()
