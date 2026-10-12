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
    check every day of the period has a published daily report
    -> synthesize_biweekly --start --end   (never --force)
    -> publish                              (builds the period's pages + hub)
    -> git add docs reports / commit / push

Safe to run twice: synthesize_biweekly exits 0 without calling the API when
the period's row already exists, and this script doesn't even get that far -
an existing row means "nothing due".

State - entirely its own, nothing shared with the daily run (pausing,
resetting or tripping one must never touch the other). All under
automation_state/:
    biweekly_state.json       last run's outcome + consecutive-failure count
    biweekly_killswitch.flag  written when the circuit breaker trips
    biweekly_pause_next.flag  one-shot manual pause (see below)
It shares run_step / do_git_sequence / send_email with daily_autorun.py as
code only, and deliberately ignores .pause_automation and killswitch.flag.

Every run ends in exactly one outcome, recorded in biweekly_state.json so
scripts/automation_control_panel.pyw can tell them apart:
    published  a period was due and its report was synthesized and pushed
    skipped    nothing was due - the normal result on most Thursdays
    failed     a period was due and no report came out of it (a step failed,
               days of the period are unpublished, or nothing was written)
    paused     a period was due but the one-shot pause flag was set
    stopped    the kill-switch flag is present; nothing was attempted

Circuit breaker: CONSECUTIVE_FAILURE_LIMIT `failed` outcomes in a row write
biweekly_killswitch.flag, try to disable the scheduled task, and say so in
the failure email; nothing runs again until a human clears the flag.
`published` and `skipped` both reset the count - `skipped` means no period
is outstanding, e.g. because the failed one was since produced by hand.
With the 8-day catch-up window a period gets at most two attempts (its own
Thursday and the next), so two failures means that period was lost.

One-shot pause: biweekly_pause_next.flag skips the next run *in which a
period is due* and is then deleted. It is left alone on nothing-due weeks -
otherwise a pause meant for next week's report would be used up by a
Thursday that was never going to do anything. (Stopping for longer is done
by disabling the scheduled task.)

Logs to automation_state/logs/biweekly_{date}.log - deliberately NOT
{date}.log, which scripts/scheduler_notify.py's 15:10 check treats as proof
that the DAILY run started that day.

    python scripts/biweekly_autorun.py                       # what the scheduled task runs
    python scripts/biweekly_autorun.py --dry-run             # report what it would do; change nothing
    python scripts/biweekly_autorun.py --dry-run --as-of 2026-10-15
"""
import argparse
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import daily_autorun as autorun  # noqa: E402  (also puts PROJECT_ROOT on sys.path)

from src.common.biweekly import latest_closed_period, missing_published_days  # noqa: E402
from src.common.db import biweekly_period_exists, get_connection, get_report_dates_in_range  # noqa: E402

CATCH_UP_DAYS = 8
GIT_PATHS = ["docs", "reports"]  # publish.py's only tracked outputs - never `add -A` at 01:30

SCHEDULED_TASK_NAME = "GeopoliticsTrackerBiweeklyAutorun"
STATE_FILE = autorun.STATE_DIR / "biweekly_state.json"
KILLSWITCH_FLAG = autorun.STATE_DIR / "biweekly_killswitch.flag"
PAUSE_NEXT_FLAG = autorun.STATE_DIR / "biweekly_pause_next.flag"

CONSECUTIVE_FAILURE_LIMIT = 2

DEFAULT_STATE = {
    "consecutive_failures": 0,
    "last_run_at": None,
    "last_outcome": None,   # published | skipped | failed | paused | stopped
    "last_detail": None,
    "last_period": None,    # "YYYY-MM-DD..YYYY-MM-DD" the run was about, if any
}


def due_period(as_of: date, period_exists) -> tuple[date, date] | None:
    """`period_exists(end_iso) -> bool` is injected so the selection rule can
    be tested without a database."""
    period = latest_closed_period(as_of, max_age_days=CATCH_UP_DAYS)
    if period is None or period_exists(period[1].isoformat()):
        return None
    return period


def missing_days_problem(conn, period: tuple[date, date]) -> str | None:
    """None when every day of the period has a published daily report;
    otherwise a sentence naming the missing dates. Same rule
    synthesize_biweekly.py enforces itself - checked here first so the
    failure email can say exactly which days, and this wrapper never passes
    --allow-missing-days: an incomplete period is a human's call."""
    start, end = period
    missing = missing_published_days(
        start, end, get_report_dates_in_range(conn, start.isoformat(), end.isoformat()),
        autorun.PROJECT_ROOT / "docs",
    )
    if not missing:
        return None
    total = (end - start).days + 1
    return f"{len(missing)} of {total} day(s) have no published daily report: {', '.join(missing)}"


def apply_outcome(state: dict, outcome: str, detail: str, period: str | None, now_iso: str) -> tuple[dict, bool]:
    """Returns (new_state, tripped). Pure - the caller does the file writes."""
    failures = state.get("consecutive_failures", 0)
    if outcome == "failed":
        failures += 1
    elif outcome in ("published", "skipped"):
        failures = 0
    new_state = {
        **DEFAULT_STATE, **state,
        "consecutive_failures": failures,
        "last_run_at": now_iso,
        "last_outcome": outcome,
        "last_detail": detail,
        "last_period": period,
    }
    return new_state, outcome == "failed" and failures >= CONSECUTIVE_FAILURE_LIMIT


def disable_scheduled_task(log) -> None:
    """Best-effort, like the daily run's: the flag file is the real stop."""
    try:
        r = subprocess.run(
            ["schtasks", "/Change", "/TN", SCHEDULED_TASK_NAME, "/Disable"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            log(f"Disabled scheduled task '{SCHEDULED_TASK_NAME}'.")
        else:
            log(f"Could not disable scheduled task '{SCHEDULED_TASK_NAME}' (exit {r.returncode}: "
                f"{(r.stderr or r.stdout).strip()}) - {KILLSWITCH_FLAG.name} still stops future runs.")
    except Exception as e:
        log(f"Could not disable scheduled task ({e!r}) - {KILLSWITCH_FLAG.name} still stops future runs.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would happen; run no step, send no email, change no state file.")
    parser.add_argument("--as-of", default=None, help="Pretend today is this YYYY-MM-DD (testing).")
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

    def finish(outcome: str, detail: str, period: str | None = None,
               subject: str | None = None, body_lines: list[str] | None = None) -> int:
        """The single exit for a real (non-dry) run: records the outcome,
        trips the breaker if this failure is one too many, sends the email."""
        state = autorun.load_json(STATE_FILE, DEFAULT_STATE)
        state, tripped = apply_outcome(state, outcome, detail, period, datetime.now().isoformat(timespec="seconds"))
        autorun.save_json(STATE_FILE, state)
        if tripped:
            KILLSWITCH_FLAG.write_text(
                f"Tripped {datetime.now().isoformat()} after {state['consecutive_failures']} "
                f"consecutive failed biweekly run(s).\n", encoding="utf-8",
            )
            log(f"KILL-SWITCH TRIPPED: {state['consecutive_failures']} consecutive failures.")
            disable_scheduled_task(log)
        if subject:
            lines = list(body_lines or [])
            lines += ["", f"Consecutive failed biweekly runs: {state['consecutive_failures']}"]
            if tripped:
                subject = f"[Geopolitics Tracker] BIWEEKLY AUTOMATION PAUSED (kill-switch) - {period or today.isoformat()}"
                lines += [
                    "",
                    "*** KILL-SWITCH TRIPPED ***",
                    f"{CONSECUTIVE_FAILURE_LIMIT} consecutive failed biweekly runs. {KILLSWITCH_FLAG.name} was written "
                    f"and the '{SCHEDULED_TASK_NAME}' task disabled (if permissions allowed). The daily run is not "
                    f"affected. Nothing biweekly runs again until you clear it - the control panel's biweekly tab "
                    f"has a reset button.",
                ]
            lines += ["", f"Log: {log_path}"]
            try:
                autorun.send_email(subject, "\n".join(lines))
            except Exception as e:
                log(f"Could not send email ({e!r}) - subject was: {subject}")
        log(f"=== biweekly_autorun.py finished: {outcome} ({detail}) ===")
        return 1 if outcome == "failed" else 0

    try:
        mode = " (DRY RUN)" if args.dry_run else ""
        log(f"=== biweekly_autorun.py starting, as of {today.isoformat()}{mode} ===")

        if KILLSWITCH_FLAG.exists():
            log(f"Stopped: {KILLSWITCH_FLAG.name} present - nothing attempted until a human clears it.")
            if args.dry_run:
                return 0
            return finish(
                "stopped", "kill-switch flag present",
                subject=f"[Geopolitics Tracker] Biweekly automation still paused (kill-switch) - {today.isoformat()}",
                body_lines=[
                    "The biweekly kill-switch tripped on an earlier run and has not been cleared.",
                    "No biweekly report was attempted tonight. The daily run is not affected.",
                    "",
                    f"To resume: investigate automation_state/logs/biweekly_*.log, then reset from the control "
                    f"panel's biweekly tab (or delete {KILLSWITCH_FLAG} and re-enable '{SCHEDULED_TASK_NAME}').",
                ],
            )

        conn = get_connection()
        try:
            period = due_period(today, lambda end: biweekly_period_exists(conn, end))
            problem = missing_days_problem(conn, period) if period else None
        finally:
            conn.close()

        if period is None:
            log("Nothing due: no closed period without a report in the catch-up window.")
            if args.dry_run:
                return 0
            return finish("skipped", "no period due")

        start, end = period[0].isoformat(), period[1].isoformat()
        label = f"{start}..{end}"
        log(f"Period due: {label} (closed {(today - period[1]).days} day(s) ago)")

        if PAUSE_NEXT_FLAG.exists():
            log(f"Paused: {PAUSE_NEXT_FLAG.name} present - skipping this one due run.")
            if args.dry_run:
                return 0
            PAUSE_NEXT_FLAG.unlink()
            log(f"Removed {PAUSE_NEXT_FLAG.name} (one-shot). Next Thursday's run will retry {label} if still missing.")
            return finish("paused", "one-shot manual pause", label)

        manual = [
            f"  python -m src.reporting.synthesize_biweekly --start {start} --end {end}",
            "  python -m src.publishing.publish",
            "  (then commit + push docs/ and reports/)",
        ]

        if problem:
            log(f"NOT RUNNING: {problem}")
            if args.dry_run:
                return 1
            return finish(
                "failed", problem, label,
                subject=f"[Geopolitics Tracker] Biweekly report {label} NOT produced",
                body_lines=[
                    f"The overnight biweekly run found period {label} due, but stopped before synthesizing:",
                    "", f"  {problem}", "",
                    "Publish the missing daily report(s) first, then run by hand:", *manual,
                    "If those days are a known, permanent gap, add --allow-missing-days to the first command.",
                    "",
                    "(Next Thursday's run will also retry on its own if the period is still missing.)",
                ],
            )

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
                    f"Biweekly trends report for {label}\n\n"
                    f"Autonomous overnight run via scripts/biweekly_autorun.py - see "
                    f"automation_state/logs/{log_path.name} for the full step-by-step record.\n"
                ),
            )

        success = ok and wrote_period
        lines = [f"Biweekly overnight run for period {label}", ""]
        for r in results:
            status = "OK" if r.ok else f"FAILED (exit={r.returncode}{', ' + r.note if r.note else ''})"
            lines.append(f"  {r.name}: {status}")
        lines.append(f"  period row in tracker.db: {'yes' if wrote_period else 'NO'}")
        lines.append(f"  git: {git_note}")
        lines += ["", f"Overall: {'SUCCESS' if success else 'FAILURE'}"]
        if success:
            return finish("published", "report synthesized, published and pushed", label,
                          subject=f"[Geopolitics Tracker] Biweekly report {label}: published", body_lines=lines)

        failed_step = next((r.name for r in results if not r.ok), None)
        if failed_step:
            detail = f"step '{failed_step}' failed"
        elif not wrote_period:
            detail = "synthesize_biweekly wrote no period row"
        else:
            detail = f"git: {git_note}"
        lines += ["", "To retry by hand:", *manual]
        return finish("failed", detail, label,
                      subject=f"[Geopolitics Tracker] Biweekly report {label}: FAILED", body_lines=lines)
    finally:
        fh.close()


if __name__ == "__main__":
    sys.exit(main())
