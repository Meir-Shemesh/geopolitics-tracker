"""Fully autonomous daily pipeline run, meant to be fired by a scheduled task
(Windows Task Scheduler) once a day with nobody watching - e.g. while the
project owner is away for several days. This is a deterministic *wrapper*
around the existing pipeline scripts (subprocess calls, checked by exit code/
timeout, never by inspecting output text and "judging" it) - it does not
re-implement or second-guess any pipeline logic itself.

Sequence (mirrors exactly what was run by hand this past week, see
PROJECT_LOG for 2026-09-27/28's manual autonomous runs):

    unittest (sanity gate) -> fetch -> pdf_health_check -> extract
    -> screen (per-file, excluding anything pdf_health_check flagged SUSPECT)
    -> analyze -> synthesize (one retry on failure) -> orphan_review (report-only)
    -> render -> publish -> git add/commit/push

    The biweekly trends report is NOT part of this run any more (moved out
    2026-10-12): it has its own scheduled task and wrapper,
    scripts/biweekly_autorun.py, firing overnight after the period's closing
    Wednesday so the report is ready Thursday morning. All this run still does
    about it is a read-only check - if a period closed at least a day ago and
    has no row in tracker.db, the daily summary email says so (see
    missing_biweekly_period_warning). That check lives here, in a separate
    process and a separate scheduled task from the overnight run, so it also
    catches the night the machine was simply off.

Failure policy (see CLAUDE.md-style reasoning in comments below):
  - A single source failing inside fetch/screen/analyze (a bad download, a
    SUSPECT file) is NOT a wrapper-level failure - that's already handled
    inside those scripts / by the per-file screening exclusion below. The
    wrapper only reacts to a *step itself* exiting non-zero or timing out.
  - synthesize.py gets exactly one retry (Stage-1 topic clustering is the
    single most fragile point in the whole pipeline per CLAUDE.md's own
    architecture notes) - if the second attempt also fails, the wrapper
    aborts the day entirely: no render, no publish, no commit. Every other
    step gets zero retries - same "don't push partial state" policy, just
    without the extra retry step.py.py.
  - The biweekly-period check is informational only and can never fail the
    day - any error inside it is swallowed and reported as "check failed".
  - Two consecutive failed days trips the kill-switch: the scheduled task
    disables itself (both a state-file flag AND the actual Windows task, so
    a stray manual re-trigger can't silently resume without notice) and an
    emergency email goes out. Nothing more happens until a human clears
    automation_state/killswitch.flag by hand.

State lives under automation_state/ (see .gitignore - never committed) and
in .pause_automation at the project root - both intentionally simple flat
files a human can inspect or edit by hand without any tooling.
"""
import json
import os
import shutil
import smtplib
import subprocess
import sys
from datetime import date, datetime
from email.mime.text import MIMEText
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from src.common import biweekly  # noqa: E402
from src.common.biweekly import PERIOD_LENGTH_DAYS, expected_rolling_window, latest_closed_period  # noqa: E402
VENV_PYTHON = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"

STATE_DIR = PROJECT_ROOT / "automation_state"
LOG_DIR = STATE_DIR / "logs"
STATE_FILE = STATE_DIR / "state.json"
CONFIG_FILE = STATE_DIR / "config.json"
KILLSWITCH_FLAG = STATE_DIR / "killswitch.flag"
PAUSE_FLAG = PROJECT_ROOT / ".pause_automation"

SCHEDULED_TASK_NAME = "GeopoliticsTrackerDailyAutorun"

CONSECUTIVE_FAILURE_LIMIT = 2  # trips the kill-switch after this many failed days in a row

# Generous per-step ceilings - not tuned to the typical case, tuned to catch a
# genuine hang (an actual WeasyPrint render.py hang was observed and manually
# killed this same week, taking ~1 hour on a date that normally renders in
# under a minute - a step that slow is never going to finish usefully inside
# an unattended run, so cutting it off and retrying tomorrow beats sitting on
# it for the rest of the vacation).
TIMEOUTS = {
    "unittest": 5 * 60,
    "fetch": 90 * 60,
    "pdf_health_check": 10 * 60,
    "extract": 45 * 60,
    # Raised from 20 min to 50 min on 2026-10-10 (see PROJECT_LOG) after a real
    # timeout: measured steady throughput is ~1.7s/page with no stalls, so even
    # a single ordinary day's extraction (714 pages that day) already brushes
    # the old 1200s ceiling - before any backlog/duplicate pages add to the
    # queue. 3000s covers a normal day plus a real backlog with headroom.
    "screen": 50 * 60,
    "analyze": 60 * 60,
    "synthesize": 20 * 60,
    "orphan_review": 5 * 60,
    # Raised 15 -> 25 min on 2026-10-13 and 25 -> 60 min on 2026-10-16 (PROJECT_LOG
    # 4.101): render time scales with the number of sections (PDF generation is
    # ~12 min per language at 137 sections). 16.10 (137 sections, the largest day
    # so far) was cut at 25 min with the German PDF still missing.
    # Raised 60 -> 120 min on 2026-10-30: 158 sections (466 articles) needed ~24 min per
    # PDF language and the run was cut at 60 min with the German PDF unfinished.
    "render": 120 * 60,
    # Used by scripts/biweekly_autorun.py (which shares run_step), not by this
    # script's own sequence. The map-reduce (Stage 1) + per-topic narrative
    # writing (Stage 2) for a full 14-day period - a few minutes for the
    # P1/P2/P3 dry-runs (see PROJECT_LOG); the ceiling is generous because no
    # live period has been timed yet and nobody is watching at 01:30. No
    # separate "render_biweekly" step exists - publish.py builds every
    # biweekly_periods row's pages on every run, same as for daily reports.
    "synthesize_biweekly": 40 * 60,
    "publish": 10 * 60,
    "git": 5 * 60,
}


def log_open(today: str):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"{today}.log"
    fh = open(path, "a", encoding="utf-8")

    def _log(msg: str) -> None:
        line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
        print(line)
        fh.write(line + "\n")
        fh.flush()

    return _log, fh, path


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return dict(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(default)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


class StepResult:
    def __init__(self, name: str, ok: bool, returncode: int | None, stdout: str, stderr: str, note: str = ""):
        self.name = name
        self.ok = ok
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.note = note


def run_step(log, name: str, args: list[str], timeout_key: str | None = None) -> StepResult:
    """Runs one `venv-python -m <module> <args>` step. Success is defined
    ONLY by exit code (0) - never by inspecting stdout text - per the
    deterministic-wrapper brief. `timeout_key` looks up TIMEOUTS; falls back
    to `name` itself if not given."""
    timeout = TIMEOUTS.get(timeout_key or name, 30 * 60)
    cmd = [str(VENV_PYTHON), "-m", *args]
    log(f"START {name}: {' '.join(cmd)} (timeout {timeout}s)")
    try:
        proc = subprocess.run(
            cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        log(f"TIMEOUT {name} after {timeout}s")
        # subprocess.run() already captured whatever reached the pipes before the kill -
        # log it exactly like the success path does, or a timeout leaves no trace of how
        # far the step actually got (see PROJECT_LOG 2026-10-10: a screen.py timeout looked
        # like a silent hang in the log, when the DB showed steady, un-stuck progress the
        # whole time - this tail was sitting in e.stdout, just never printed).
        if e.stdout:
            log(f"  --- {name} stdout (tail, before timeout) ---\n" + "\n".join(e.stdout.splitlines()[-40:]))
        if e.stderr:
            log(f"  --- {name} stderr (tail, before timeout) ---\n" + "\n".join(e.stderr.splitlines()[-40:]))
        return StepResult(name, False, None, e.stdout or "", e.stderr or "", note=f"timed out after {timeout}s")
    ok = proc.returncode == 0
    log(f"{'OK' if ok else 'FAIL'} {name} (exit {proc.returncode})")
    if proc.stdout:
        log(f"  --- {name} stdout (tail) ---\n" + "\n".join(proc.stdout.splitlines()[-40:]))
    if not ok and proc.stderr:
        log(f"  --- {name} stderr (tail) ---\n" + "\n".join(proc.stderr.splitlines()[-40:]))
    return StepResult(name, ok, proc.returncode, proc.stdout, proc.stderr)


def run_git(log, args: list[str]) -> StepResult:
    cmd = ["git", *args]
    log(f"START git {' '.join(args)}")
    try:
        proc = subprocess.run(
            cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=TIMEOUTS["git"],
        )
    except subprocess.TimeoutExpired as e:
        log(f"TIMEOUT git {' '.join(args)}")
        return StepResult("git", False, None, e.stdout or "", e.stderr or "", note="timed out")
    ok = proc.returncode == 0
    log(f"{'OK' if ok else 'FAIL'} git {' '.join(args)} (exit {proc.returncode})\n{proc.stdout}\n{proc.stderr}")
    return StepResult("git", ok, proc.returncode, proc.stdout, proc.stderr)


def do_git_sequence(
    log, today: str, paths: list[str] | None = None, commit_message: str | None = None,
) -> tuple[bool, str]:
    """`paths` narrows staging to those paths (`git add -- <paths>`) instead of
    the default `git add -A`; `commit_message` replaces the daily message.
    Both exist for scripts/biweekly_autorun.py - the defaults are this
    script's own unchanged behaviour.

    Returns (ok, note). 'nothing to commit' is a normal, successful
    outcome (not every day necessarily changes tracked output), never a
    failure. A remote that has moved on (fetch shows we're behind) is
    deliberately NOT auto-merged/rebased here - that's judged too risky for
    an unattended run; it's surfaced as a failure so a human resolves it by
    hand, exactly like every other "don't push partial/uncertain state"
    case."""
    add = run_git(log, ["add", "-A"] if paths is None else ["add", "--", *paths])
    if not add.ok:
        return False, "git add failed"

    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=str(PROJECT_ROOT), timeout=TIMEOUTS["git"],
    )
    if diff.returncode == 0:
        log("git: nothing staged - nothing to commit today")
        return True, "nothing to commit"

    msg_path = STATE_DIR / "commit_msg.txt"
    msg_path.write_text(
        commit_message or (
            f"Daily automated report for {today}\n\n"
            f"Autonomous run via scripts/daily_autorun.py - see automation_state/logs/{today}.log "
            f"for the full step-by-step record.\n\n"
            f"Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>\n"
        ),
        encoding="utf-8",
    )
    commit = run_git(log, ["commit", "-F", str(msg_path)])
    if not commit.ok:
        return False, "git commit failed"

    fetch = run_git(log, ["fetch", "origin"])
    if not fetch.ok:
        return False, "git fetch failed"
    status = subprocess.run(
        ["git", "status", "-sb"], cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=TIMEOUTS["git"],
    )
    if "behind" in status.stdout:
        log(f"git: local branch is behind origin/main - not auto-merging. status: {status.stdout.strip()}")
        return False, "local branch behind origin/main - needs a human to reconcile"

    push = run_git(log, ["push", "origin", "main"])
    if not push.ok:
        return False, "git push failed"
    return True, "committed and pushed"


def send_email(subject: str, body: str) -> None:
    address = os.environ.get("AUTOMATION_GMAIL_ADDRESS")
    app_password = os.environ.get("AUTOMATION_GMAIL_APP_PASSWORD")
    to_address = os.environ.get("AUTOMATION_ALERT_TO", address or "")
    if not address or not app_password or not to_address:
        print("EMAIL NOT SENT (missing AUTOMATION_GMAIL_ADDRESS/AUTOMATION_GMAIL_APP_PASSWORD/"
              "AUTOMATION_ALERT_TO in .env) - printing body instead:\n")
        print(f"Subject: {subject}\n\n{body}")
        return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = address
    msg["To"] = to_address
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=60) as server:
        server.starttls()
        server.login(address, app_password)
        server.sendmail(address, [to_address], msg.as_string())


def disable_scheduled_task(log) -> None:
    """Best-effort - a permissions failure here must never itself crash the
    wrapper (the killswitch.flag file is the real, always-effective stop;
    disabling the Task Scheduler entry too is belt-and-suspenders)."""
    try:
        subprocess.run(
            ["schtasks", "/Change", "/TN", SCHEDULED_TASK_NAME, "/Disable"],
            capture_output=True, text=True, timeout=30,
        )
        log(f"Disabled scheduled task '{SCHEDULED_TASK_NAME}' via schtasks.")
    except Exception as e:
        log(f"Could not disable scheduled task automatically ({e!r}) - killswitch.flag still stops future runs.")


def missing_biweekly_period_warning(today: date) -> str:
    """One line for the daily summary email. Read-only - never synthesizes
    anything itself. Only looks one period back: once the next one closes,
    an old gap stops being this run's news (publish.py's hub simply lists
    whatever periods exist)."""
    try:
        if biweekly.ROLLING_WINDOW_ENABLED:
            # Rolling mode: every Thursday's overnight run should have produced the window ending the
            # day before it - that, not "a fixed period closed", is what can be missing.
            period = expected_rolling_window(today)
        else:
            period = latest_closed_period(today, max_age_days=PERIOD_LENGTH_DAYS)
        if period is None:
            return "no closed period to check"
        start, end = period[0].isoformat(), period[1].isoformat()
        from src.common.db import biweekly_period_exists, get_connection
        conn = get_connection()
        try:
            exists = biweekly_period_exists(conn, end)
        finally:
            conn.close()
        if exists:
            return f"latest closed period {start}..{end} is in tracker.db"
        return (
            f"*** WARNING: period {start}..{end} ended {(today - period[1]).days} day(s) ago and has NO "
            f"report in tracker.db - the overnight run (scripts/biweekly_autorun.py) did not produce it. "
            f"Check automation_state/logs/biweekly_*.log, or run it by hand: "
            f"python -m src.reporting.synthesize_biweekly --start {start} --end {end} ***"
        )
    except Exception as e:
        return f"check failed ({e!r})"


# Daily synthesize input (articles of one report date) above which the run only WARNS. Stage 1 groups all of a
# day's articles in one call; 380 was the largest success ever measured and the ceiling is estimated at
# ~450-480 (CLAUDE.md, "השלכות ידועות" 1), so the threshold sits conservatively below. Never blocks.
SYNTHESIS_VOLUME_WARN_THRESHOLD = 320


def record_screening_holds(log, entries: list[dict]) -> None:
    """Persist why each file was kept out of screening, so a later report_date shift can explain itself."""
    from src.common.db import get_connection, record_screening_hold
    conn = get_connection()
    try:
        for entry in entries:
            record_screening_hold(conn, entry["id"], entry.get("reason") or "excluded from screening by the daily run")
    except Exception as e:  # the hold reason is bookkeeping - never fail the day over it
        log(f"Could not record screening hold reasons ({e!r}).")
    finally:
        conn.close()


def report_date_shift_notes(today: str) -> list[str]:
    """One line per file whose report_date was moved onto `today` by its first screening (db.claim_report_date_on_first_scan)."""
    try:
        from src.common.db import get_connection, get_report_date_shifts
        conn = get_connection()
        try:
            rows = get_report_date_shifts(conn, today)
        finally:
            conn.close()
        notes = []
        for r in rows:
            reason = r["screening_hold_reason"] or (
                f"no reason recorded - not screened on its download day (downloaded "
                f"{datetime.fromisoformat(r['downloaded_at']).astimezone():%H:%M} local)"
            )
            notes.append(f"{r['newspaper']} / {r['file_name']}: download-day report {r['report_date_original']} -> "
                         f"first screened {r['report_date']} ({reason})")
        return notes
    except Exception as e:
        return [f"check failed ({e!r})"]


def synthesis_volume_note(today: str) -> tuple[str, bool]:
    """(text, is_warning) - how many articles synthesize will receive for `today`."""
    try:
        from src.common.db import count_articles_for_date, get_connection
        conn = get_connection()
        try:
            n = count_articles_for_date(conn, today)
        finally:
            conn.close()
    except Exception as e:
        return f"check failed ({e!r})", False
    if n > SYNTHESIS_VOLUME_WARN_THRESHOLD:
        return (f"*** WARNING: unusual synthesize input volume ({n} articles, above the {SYNTHESIS_VOLUME_WARN_THRESHOLD} "
                f"threshold; the largest day ever verified was 380, the estimated ceiling is ~450-480) - "
                f"check the result by hand before approving ***"), True
    return f"{n} articles (threshold {SYNTHESIS_VOLUME_WARN_THRESHOLD})", False


def load_env() -> None:
    """Same convention as every pipeline script - python-dotenv from .env at
    the project root, no new dependency (already in requirements.txt)."""
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")


def main() -> int:
    load_env()
    today = date.today().isoformat()
    log, fh, log_path = log_open(today)
    log(f"=== daily_autorun.py starting for {today} ===")

    try:
        if PAUSE_FLAG.exists():
            log(f"Skipped: {PAUSE_FLAG.name} present (manual pause). Not counted as a failure, no email sent.")
            return 0

        if KILLSWITCH_FLAG.exists():
            log("Skipped: killswitch.flag present from an earlier run - automation stays off until a human "
                "clears it by hand (delete the file, and re-enable the scheduled task if it was disabled).")
            send_email(
                f"[Geopolitics Tracker] Automation still paused (kill-switch) - {today}",
                f"The kill-switch tripped on an earlier day and hasn't been cleared yet.\n"
                f"No pipeline run was attempted today.\n\n"
                f"To resume: delete {KILLSWITCH_FLAG} and re-enable the '{SCHEDULED_TASK_NAME}' scheduled task, "
                f"then investigate the failures logged under automation_state/logs/ first.\n",
            )
            return 0

        config = load_json(CONFIG_FILE, {"remaining_runs": None, "end_date": None})
        if config.get("end_date") and today > config["end_date"]:
            log(f"Stopping: end_date {config['end_date']} has passed.")
            disable_scheduled_task(log)
            send_email(
                f"[Geopolitics Tracker] Automation window ended - {today}",
                f"config.json's end_date ({config['end_date']}) has passed. The scheduled task has been "
                f"disabled (no pipeline run happened today). Edit automation_state/config.json and "
                f"re-enable the scheduled task if you want it to keep running.\n",
            )
            return 0
        if config.get("remaining_runs") is not None and config["remaining_runs"] <= 0:
            log("Stopping: remaining_runs quota exhausted.")
            disable_scheduled_task(log)
            send_email(
                f"[Geopolitics Tracker] Automation run quota exhausted - {today}",
                f"config.json's remaining_runs reached 0. The scheduled task has been disabled (no pipeline "
                f"run happened today). Edit automation_state/config.json and re-enable the scheduled task "
                f"if you want it to keep running.\n",
            )
            return 0

        state = load_json(STATE_FILE, {"consecutive_failures": 0, "last_run_date": None, "last_run_status": None})
        results: dict[str, StepResult] = {}
        day_ok = True

        # --- sanity gate ---
        r = run_step(log, "unittest", ["unittest", "discover", "-s", "tests"], timeout_key="unittest")
        results["unittest"] = r
        day_ok = r.ok

        # --- ingestion + corruption pre-screen ---
        if day_ok:
            r = run_step(log, "fetch", ["src.ingestion.fetch"])
            results["fetch"] = r
            day_ok = r.ok

        suspects: list[dict] = []
        good_files: list[dict] = []
        if day_ok:
            # --date (not the default pending-only scope) so this is robust even if something
            # already extracted one of today's files before this step ran (observed once in
            # testing - see scripts/pdf_health_check.py's --date docstring for why).
            r = run_step(log, "pdf_health_check", ["scripts.pdf_health_check", "--date", today, "--json"])
            results["pdf_health_check"] = r
            day_ok = r.ok
            if day_ok:
                try:
                    summary = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
                    suspects = summary.get("suspects", [])
                    good_files = summary.get("ok", [])
                    for w in summary.get("warnings", []):
                        log(f"pdf_health_check WARNING (non-blocking, file is screened as usual): {w['file_name']} - {w['reason']}")
                    if suspects:
                        record_screening_holds(log, suspects)
                except Exception as e:
                    log(f"Could not parse pdf_health_check --json output ({e!r}) - treating as no suspects, "
                        f"screen.py will run its normal blanket pass.")

        if day_ok:
            r = run_step(log, "extract", ["src.extraction.extract"])
            results["extract"] = r
            day_ok = r.ok

        if day_ok:
            if suspects:
                names = ", ".join(s["file_name"] for s in suspects)
                log(f"pdf_health_check flagged {len(suspects)} SUSPECT file(s), excluded from screening: {names}")
                screen_ok = True
                for entry in good_files:
                    r = run_step(log, "screen", ["src.analysis.screen", "--file", entry["file_name"]])
                    screen_ok = screen_ok and r.ok
                results["screen"] = StepResult("screen", screen_ok, None, "", "")
                day_ok = screen_ok
            else:
                r = run_step(log, "screen", ["src.analysis.screen"])
                results["screen"] = r
                day_ok = r.ok

        shift_notes = report_date_shift_notes(today)
        for note in shift_notes:
            log(f"REPORT_DATE_SHIFT: {note}")

        if day_ok:
            r = run_step(log, "analyze", ["src.analysis.analyze"])
            results["analyze"] = r
            day_ok = r.ok

        volume_note = "not checked (an earlier step failed)"
        # --- synthesize: exactly one retry, then abort-the-day on failure ---
        if day_ok:
            volume_note, _ = synthesis_volume_note(today)
            log(f"Synthesize input volume: {volume_note}")
            r = run_step(log, "synthesize", ["src.reporting.synthesize", "--date", today])
            if not r.ok:
                log("synthesize failed once - retrying (allowed exactly once per the failure policy).")
                r = run_step(log, "synthesize", ["src.reporting.synthesize", "--date", today])
            results["synthesize"] = r
            day_ok = r.ok
            if not day_ok:
                log("synthesize failed twice - aborting today's run entirely (no render/publish/git).")

        if day_ok:
            r = run_step(log, "orphan_review", ["scripts.orphan_review"])
            results["orphan_review"] = r  # informational only - never fails the day (see CLAUDE.md: report, don't fix silently)

        if day_ok:
            r = run_step(log, "render", ["src.reporting.render", "--date", today])
            results["render"] = r
            day_ok = r.ok

        biweekly_note = missing_biweekly_period_warning(date.fromisoformat(today))
        log(f"Biweekly period check: {biweekly_note}")

        if day_ok:
            r = run_step(log, "publish", ["src.publishing.publish"])
            results["publish"] = r
            day_ok = r.ok

        git_note = "not attempted (an earlier step failed)"
        if day_ok:
            git_ok, git_note = do_git_sequence(log, today)
            day_ok = git_ok

        # --- state + kill-switch ---
        if day_ok:
            state["consecutive_failures"] = 0
        else:
            state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
        state["last_run_date"] = today
        state["last_run_status"] = "success" if day_ok else "failure"
        save_json(STATE_FILE, state)

        if config.get("remaining_runs") is not None:
            config["remaining_runs"] -= 1
            save_json(CONFIG_FILE, config)

        killswitch_tripped = False
        if state["consecutive_failures"] >= CONSECUTIVE_FAILURE_LIMIT:
            killswitch_tripped = True
            KILLSWITCH_FLAG.parent.mkdir(parents=True, exist_ok=True)
            KILLSWITCH_FLAG.write_text(
                f"Tripped {datetime.now().isoformat()} after "
                f"{state['consecutive_failures']} consecutive failed day(s).\n",
                encoding="utf-8",
            )
            disable_scheduled_task(log)

        # --- email summary ---
        lines = [f"Daily automation run for {today}", ""]
        for name, r in results.items():
            if isinstance(r, StepResult):
                status = "OK" if r.ok else f"FAILED (exit={r.returncode}{', ' + r.note if r.note else ''})"
            else:
                status = "?"
            lines.append(f"  {name}: {status}")
        lines.append(f"  biweekly check: {biweekly_note}")
        lines.append(f"  synthesize input volume: {volume_note}")
        if shift_notes:
            lines.append(f"  *** WARNING: {len(shift_notes)} file(s) joined today's report because they were first screened "
                         f"after their download day (not screened on the day they were downloaded): ***")
            lines += [f"    - {note}" for note in shift_notes]
        else:
            lines.append("  report_date shifts: none")
        lines.append(f"  git: {'OK' if day_ok else 'FAILED'} ({git_note})")
        lines += [
            "",
            f"Overall: {'SUCCESS' if day_ok else 'FAILURE'}",
            f"Consecutive failed days: {state['consecutive_failures']}",
        ]
        if config.get("remaining_runs") is not None:
            lines.append(f"Remaining scheduled runs after today: {config['remaining_runs']}")
        if killswitch_tripped:
            lines += [
                "",
                "*** KILL-SWITCH TRIPPED ***",
                f"{CONSECUTIVE_FAILURE_LIMIT} consecutive failed days reached - the scheduled task has been "
                f"disabled and automation_state/killswitch.flag written. Nothing more will run automatically "
                f"until you investigate and clear it by hand.",
            ]
        lines += ["", f"Full log: {log_path}"]
        subject = f"[Geopolitics Tracker] Daily run {'OK' if day_ok else 'FAILED'} - {today}"
        if killswitch_tripped:
            subject = f"[Geopolitics Tracker] AUTOMATION PAUSED (kill-switch) - {today}"
        send_email(subject, "\n".join(lines))

        log(f"=== daily_autorun.py finished for {today}: {'success' if day_ok else 'failure'} ===")
        return 0 if day_ok else 1
    finally:
        fh.close()


if __name__ == "__main__":
    sys.exit(main())
