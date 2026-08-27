"""One-off backfill: recompute reports.sources_included for all existing dates.

get_sources_for_date() used to derive sources from downloaded_files alone, so a
source that downloaded successfully but yielded zero articles (e.g. an image-only
scanned PDF) still showed up in the report's "sources covered" badge. Now that the
function joins through articles, this recomputes the already-stored column for
every existing report using the fixed query - no re-synthesis, no API calls.
"""

from src.common.db import get_all_reports, get_connection, get_sources_for_date, init_db

import json


def run() -> None:
    conn = get_connection()
    init_db(conn)

    reports = get_all_reports(conn)
    changed = 0

    for report in reports:
        report_date = report["report_date"]
        old_sources = json.loads(report["sources_included"])
        new_sources = get_sources_for_date(conn, report_date)

        if new_sources != old_sources:
            conn.execute(
                "UPDATE reports SET sources_included = ? WHERE report_date = ?",
                (json.dumps(new_sources), report_date),
            )
            changed += 1
            print(f"  {report_date}: {old_sources} -> {new_sources}")
        else:
            print(f"  {report_date}: unchanged ({new_sources})")

    conn.commit()
    conn.close()
    print(f"\nDone: {changed}/{len(reports)} report(s) updated.")


if __name__ == "__main__":
    run()
