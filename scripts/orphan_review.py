"""Read-only review: articles that were analyzed but never reached any report.

Permanent tool (unlike the other one-off scripts here): run it after Synthesize to check the rule in
CLAUDE.md - every article of the new ingestion must be in a report, so the orphan count must be 0.

    python -m scripts.orphan_review

It opens tracker.db read-only and changes nothing. Sections:
  A. totals, and orphans per newspaper
  B. orphans classified by cause, per file
       cat 1 = no report exists for the article's upload day (date(published_at))
       cat 2 = a report exists for that day but the article was analyzed AFTER it was built (stranded)
       cat 3 = the article existed BEFORE that report was built, yet is missing from it (unexpected)
  C. simulation of the report-date rule over the archive: run days that would mix several upload days
  D. decision support: local-vs-UTC download day, and download day vs first-analysis day
  E. hypothetical rescue of the current orphans under the rule (only meaningful while orphans exist)

History: written for the 2026-09-20 review that found 308 orphans (9.7% of the archive, 163 of them
Economist) - PROJECT_LOG 4.43/4.44. Sections C and D are simulations over the whole history and keep
their meaning after the fix; sections B and E are empty once there are no orphans.
"""

import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime

from src.common.db import DB_PATH

sys.stdout.reconfigure(encoding="utf-8")


def utc_day(stamp: str) -> str:
    return datetime.fromisoformat(stamp).date().isoformat()


def local_day(stamp: str) -> str:
    return datetime.fromisoformat(stamp).astimezone().date().isoformat()  # system timezone


def run() -> None:
    conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    reports = {r["report_date"]: r["created_at"] for r in conn.execute("SELECT report_date, created_at FROM reports")}
    arts = conn.execute(
        """
        SELECT a.id, a.newspaper, a.file_id, a.page_number, a.analyzed_at,
               df.file_name, df.published_at, df.downloaded_at,
               EXISTS (SELECT 1 FROM report_section_articles r WHERE r.article_id = a.id) AS in_report
        FROM articles a JOIN downloaded_files df ON df.id = a.file_id
        """
    ).fetchall()
    orphans = [a for a in arts if not a["in_report"]]

    # ---------------------------------------------------------------- A
    print("=" * 78)
    print("A. TOTALS")
    pct = len(orphans) / len(arts) * 100 if arts else 0
    print(f"articles total: {len(arts)} | in a report: {len(arts) - len(orphans)} | NEVER in any report: {len(orphans)} ({pct:.1f}%)")
    print("\nOrphans per newspaper:")
    for paper, n in Counter(a["newspaper"] for a in orphans).most_common():
        print(f"  {paper:32s} {n:5d}   (of {sum(1 for a in arts if a['newspaper'] == paper)} analyzed)")
    if not orphans:
        print("  none")

    # ---------------------------------------------------------------- B
    print("\n" + "=" * 78)
    print("B. ORPHANS BY FILE, CLASSIFIED BY CAUSE (cat 1 = no report that day, 2 = analyzed after the report was built, 3 = unexpected)")

    def cat(a) -> int:
        day = utc_day(a["published_at"])
        if day not in reports:
            return 1
        return 2 if a["analyzed_at"] > reports[day] else 3

    groups = defaultdict(list)
    for a in orphans:
        groups[(cat(a), utc_day(a["published_at"]), a["file_id"], a["newspaper"], a["file_name"])].append(a)
    cat_totals = Counter()
    for (k, *_), items in groups.items():
        cat_totals[k] += len(items)
    print("totals by category: " + (", ".join(f"cat {k}: {v}" for k, v in sorted(cat_totals.items())) or "none"))
    for k in (1, 2, 3):
        rows = [(key, items) for key, items in sorted(groups.items()) if key[0] == k]
        if not rows:
            continue
        print(f"\n--- category {k} ({cat_totals[k]} articles, {len(rows)} files)")
        print(f"  {'upload day':11s} {'file':>4s} {'articles':>8s}  {'newspaper':24s} {'downloaded(local)':17s} file name")
        for (_, day, fid, paper, fname), items in rows:
            print(f"  {day:11s} {fid:4d} {len(items):8d}  {paper:24s} {local_day(items[0]['downloaded_at']):17s} {fname[:52]}")

    # ---------------------------------------------------------------- C
    print("\n" + "=" * 78)
    print("C. SIMULATION: report day = local date of download (pipeline run day), over the whole archive")
    print("   'span' = days between the oldest and newest upload day inside one run day; 'upload-day count' includes orphans")
    files = conn.execute(
        """SELECT df.id, df.newspaper, df.published_at, df.downloaded_at, COUNT(a.id) AS n_articles
           FROM downloaded_files df LEFT JOIN articles a ON a.file_id = df.id GROUP BY df.id"""
    ).fetchall()
    by_run = defaultdict(list)
    for f in files:
        if f["n_articles"]:
            by_run[local_day(f["downloaded_at"])].append(f)
    upload_day_counts = Counter(utc_day(a["published_at"]) for a in arts)

    print(f"\n  {'run day':10s} {'articles':>8s} {'upload-day':>10s} {'upload days mixed (day:articles)'}")
    backlog_days, spans = [], Counter()
    for run_day in sorted(by_run):
        nominal = Counter()
        for f in by_run[run_day]:
            nominal[utc_day(f["published_at"])] += f["n_articles"]
        days = sorted(nominal)
        span = (datetime.fromisoformat(days[-1]) - datetime.fromisoformat(days[0])).days
        spans[span] += 1
        if span >= 2:
            backlog_days.append(run_day)
        mark = "  <== BACKLOG (span>=2)" if span >= 2 else ("  (span 1)" if span == 1 else "")
        mix = ", ".join(f"{d[5:]}:{nominal[d]}" for d in days)
        print(f"  {run_day:10s} {sum(nominal.values()):8d} {upload_day_counts.get(run_day, 0):10d}  {mix}{mark}")
    print(f"\n  run days with a backlog mix (span >= 2 days): {backlog_days or 'none'}")
    print(f"  run days by span: {dict(sorted(spans.items()))}  (of {len(by_run)} run days with articles)")

    # ---------------------------------------------------------------- D
    print("\n" + "=" * 78)
    print("D. DECISION SUPPORT")
    with_articles = [f for f in files if f["n_articles"]]
    diff_tz = [f for f in with_articles if local_day(f["downloaded_at"]) != utc_day(f["downloaded_at"])]
    print(f"  files whose LOCAL download day != UTC download day: {len(diff_tz)} of {len(with_articles)}")
    first_analysis = {r["file_id"]: r["m"] for r in conn.execute("SELECT file_id, MIN(analyzed_at) AS m FROM articles GROUP BY file_id")}
    diff_an = [f for f in files if f["id"] in first_analysis and local_day(f["downloaded_at"]) != local_day(first_analysis[f["id"]])]
    print(f"  files whose LOCAL download day != local day of first analysis: {len(diff_an)} of {len(first_analysis)}")
    mismatch_by_day = Counter(local_day(f["downloaded_at"]) for f in diff_an)
    downloads_by_day = Counter(local_day(f["downloaded_at"]) for f in files if f["id"] in first_analysis)
    for day in sorted(mismatch_by_day):
        print(f"     {day}: {mismatch_by_day[day]} of {downloads_by_day[day]} files analyzed on a different local day than downloaded")
    print(f"  system local tz offset now: {datetime.now().astimezone().strftime('%z')}")

    # ---------------------------------------------------------------- E
    print("\n" + "=" * 78)
    print("E. HYPOTHETICAL RESCUE OF THE CURRENT ORPHANS UNDER THE RULE")
    if not orphans:
        print("  no orphans - nothing to rescue")
    res = defaultdict(list)
    for a in orphans:
        run_day = local_day(a["downloaded_at"])
        if run_day not in reports:
            res["no report exists for the run day"].append(a)
        elif a["analyzed_at"] <= reports[run_day]:
            res["rescued (analyzed before the run-day report was built)"].append(a)
        else:
            res["STILL stranded (analyzed after the run-day report was built)"].append(a)
    for label, items in res.items():
        print(f"\n  {label}: {len(items)} articles")
        per = Counter((a["file_id"], a["newspaper"], a["file_name"][:40], local_day(a["downloaded_at"])) for a in items)
        for (fid, paper, fname, run_day), n in sorted(per.items()):
            print(f"     file {fid:3d} run-day {run_day} {n:4d}  {paper}: {fname}")

    print("\n" + "=" * 78)
    print(f"VERDICT: {len(orphans)} orphan article(s) - " + ("OK" if not orphans else "REPORT IT (do not fix silently: changing a report date rewrites published reports)"))
    conn.close()


if __name__ == "__main__":
    run()
