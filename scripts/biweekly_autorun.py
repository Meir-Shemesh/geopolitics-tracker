"""Unattended overnight run of the biweekly trends report, fired by its own
scheduled task (GeopoliticsTrackerBiweeklyAutorun, Thursdays 01:30 local) -
separate from scripts/daily_autorun.py's 15:00 task since 2026-10-12.

A biweekly period ends with Wednesday's daily report. This runs a few hours
later, in the night between Wednesday and Thursday, so the report is
published by Thursday morning. The task fires EVERY Thursday; on the weeks
that don't follow a closing Wednesday this script finds nothing due and
exits without doing (or emailing) anything - the real work happens one
Thursday in two.

Which period: the most recent one that ended before today, if it has no row
in tracker.db yet and ended at most CATCH_UP_DAYS ago. Asking "did a period
close TODAY" (src.common.biweekly.period_closing_on) would be wrong here -
after midnight "today" is already Thursday, the first day of the next
period. The catch-up window is 8 days so that a missed night (machine off)
is picked up by the following Thursday's firing instead of being lost.

Sequence, when a period is due:
    check Wednesday's daily report exists and is published
    -> synthesize_biweekly --start --end   (never --force)
    -> publish                              (builds the period's pages + hub)
    -> git add docs reports / commit / push

Safe to run twice: synthesize_biweekly exits 0 without calling the API when
the period's row already exists, and this script doesn't even get that far -
an existing row means "nothing due".

Shares run_step / do_git_sequence / send_email with daily_autorun.py, but
none of its state: a failure here never touches the daily consecutive-
failure counter or its kill-switch. It does honour both stop flags
(.pause_automation, automation_state/killswitch.flag).

Logs to automation_state/logs/biweekly_{date}.log - deliberately NOT
{date}.log, which scripts/scheduler_notify.py's 15:10 check treats as proof
that the DAILY run started that day.

    python scripts/biweekly_autorun.py                       # what the scheduled task runs
    python scripts/biweekly_autorun.py --dry-run             # report what it would do, do nothing
    python scripts/biweekly_autorun.py --dry-run --as-of 2026-10-15
"""
import argparse
import sys
from datetime import date, datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import daily_autorun as autorun  # noqa: E402  (also puts PROJECT_ROOT on sys.path)

from src.common.biweekly import latest_closed_period  # noqa: E402
from src.common.db import biweekly_period_exists, get_connection, report_exists  # noqa: E402

CATCH_UP_DAYS = 8
GIT_PATHS = ["docs", "reports"]  # publish.py's only tracked outputs - never `add -A` at 01:30


def due_period(as_of: date, period_exists) -> tuple[date, date] | None:
    """`period_exists(end_iso) -> bool` is injected so the selection rule can
    be tested without a database."""
    period = latest_closed_period(as_of, max_age_days=CATCH_UP_DAYS)
    if period is None or period_exists(period[1].isoformat()):
        return None
    return period


def closing_day_report_problem(conn, end: str) -> str | None:
    """None when Wednesday's daily report is both in tracker.db and already
    published; otherwise the reason. Synthesizing without it would quietly
    produce a 13-day report under a 14-day label."""
    if not report_exists(conn, end):
        return f"no daily report for {end} in tracker.db"
    published = autorun.PROJECT_ROOT / "docs" / "he" / f"report_{end}_he.html"
    if not published.exists():
        return f"daily report for {end} is in tracker.db but not published ({published.name} missing from docs/he/)"
    return None


def notify(log, subject: str, body: str) -> None:
    try:
        autorun.send_email(subject, body)
    except Exception as e:
        log(f"Could not send email ({e!r}) - subject was: {subject}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Report what would happen; run no step, send no email.")
    parser.add_argument("--as-of", default=None, help="Pretend today is this YYYY-MM-DD (testing; implies nothing else).")
    args = parser.parse_args()

    autorun.load_env()
    today = date.fromisoformat(args.as_of) if args.as_of else date.today()

    autorun.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = autorun.LOG_DIR / f"biweekly_{date.today().isoformat()}.log"
    fh = open(log_path, "a", encoding="utf-8")

    def log(msg: str) -> None:
        line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
        print(line)
        fh.write(line + "\n")
        fh.flush()

    try:
        mode = " (DRY RUN)" if args.dry_run else ""
        log(f"=== biweekly_autorun.py starting, as of {today.isoformat()}{mode} ===")

        if autorun.PAUSE_FLAG.exists():
            log(f"Skipped: {autorun.PAUSE_FLAG.name} present (manual pause).")
            return 0
        if autorun.KILLSWITCH_FLAG.exists():
            log("Skipped: killswitch.flag present - automation is stopped until a human clears it.")
            return 0

        conn = get_connection()
        try:
            period = due_period(today, lambda end: biweekly_period_exists(conn, end))
            if period is None:
                log("Nothing due: no closed period without a report in the catch-up window.")
                return 0
            start, end = period[0].isoformat(), period[1].isoformat()
            log(f"Period due: {start}..{end} (closed {(today - period[1]).days} day(s) ago)")
            problem = closing_day_report_problem(conn, end)
        finally:
            conn.close()

        if problem:
            log(f"NOT RUNNING: {problem}")
            if not args.dry_run:
                notify(
                    log,
                    f"[geopolitics-tracker] Biweekly report {start}..{end} NOT produced",
                    f"The overnight biweekly run found period {start}..{end} due, but stopped before "
                    f"synthesizing:\n\n  {problem}\n\n"
                    f"Fix the daily report for {end} first, then run by hand:\n"
                    f"  python -m src.reporting.synthesize_biweekly --start {start} --end {end}\n"
                    f"  python -m src.publishing.publish\n\n"
                    f"(Next Thursday's run will also retry on its own if the period is still missing.)\n\n"
                    f"Log: {log_path}",
                )
            return 1

        if args.dry_run:
            log(f"DRY RUN: would run synthesize_biweekly --start {start} --end {end}, then publish, "
                f"then git add {' '.join(GIT_PATHS)} / commit / push.")
            return 0

        results = []
        ok = True
        for name, step_args in (
            ("synthesize_biweekly", ["src.reporting.synthesize_biweekly", "--start", start, "--end", end]),
            ("publish", ["src.publishing.publish"]),
        ):
            r = autorun.run_step(log, name, step_args)
            results.append(r)
            if not r.ok:
                ok = False
                break

        # synthesize_biweekly exits 0 for "no topic cleared the threshold" too -
        # only a row in the DB means a report actually exists.
        wrote_period = False
        if ok:
            conn = get_connection()
            try:
                wrote_period = biweekly_period_exists(conn, end)
            finally:
                conn.close()
            if not wrote_period:
                log(f"synthesize_biweekly exited 0 but wrote no period row for {end} - see its output above.")

        git_note = "not attempted (an earlier step failed)"
        if ok:
            ok, git_note = autorun.do_git_sequence(
                log, today.isoformat(), paths=GIT_PATHS,
                commit_message=(
                    f"Biweekly trends report for {start}..{end}\n\n"
                    f"Autonomous overnight run via scripts/biweekly_autorun.py - see "
                    f"automation_state/logs/{log_path.name} for the full step-by-step record.\n"
                ),
            )

        success = ok and wrote_period
        lines = [f"Biweekly overnight run for period {start}..{end}", ""]
        for r in results:
            status = "OK" if r.ok else f"FAILED (exit={r.returncode}{', ' + r.note if r.note else ''})"
            lines.append(f"  {r.name}: {status}")
        lines.append(f"  period row in tracker.db: {'yes' if wrote_period else 'NO'}")
        lines.append(f"  git: {git_note}")
        lines += ["", f"Overall: {'SUCCESS' if success else 'FAILURE'}", f"Log: {log_path}"]
        if not success:
            lines += [
                "",
                "To retry by hand:",
                f"  python -m src.reporting.synthesize_biweekly --start {start} --end {end}",
                "  python -m src.publishing.publish",
                "  (then commit + push docs/ and reports/)",
            ]
        notify(
            log,
            f"[geopolitics-tracker] Biweekly report {start}..{end}: {'published' if success else 'FAILED'}",
            "\n".join(lines),
        )
        log(f"=== biweekly_autorun.py finished: {'success' if success else 'failure'} ===")
        return 0 if success else 1
    finally:
        fh.close()


if __name__ == "__main__":
    sys.exit(main())
