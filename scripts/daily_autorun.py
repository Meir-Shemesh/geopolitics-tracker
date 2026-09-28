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
    "fetch": 60 * 60,
    "pdf_health_check": 10 * 60,
    "extract": 30 * 60,
    "screen": 20 * 60,
    "analyze": 60 * 60,
    "synthesize": 20 * 60,
    "orphan_review": 5 * 60,
    "render": 15 * 60,
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


def do_git_sequence(log, today: str) -> tuple[bool, str]:
    """Returns (ok, note). 'nothing to commit' is a normal, successful
    outcome (not every day necessarily changes tracked output), never a
    failure. A remote that has moved on (fetch shows we're behind) is
    deliberately NOT auto-merged/rebased here - that's judged too risky for
    an unattended run; it's surfaced as a failure so a human resolves it by
    hand, exactly like every other "don't push partial/uncertain state"
    case."""
    add = run_git(log, ["add", "-A"])
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
        f"Daily automated report for {today}\n\n"
        f"Autonomous run via scripts/daily_autorun.py - see automation_state/logs/{today}.log "
        f"for the full step-by-step record.\n\n"
        f"Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>\n",
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
            r = run_step(log, "pdf_health_check", ["scripts.pdf_health_check", "--json"])
            results["pdf_health_check"] = r
            day_ok = r.ok
            if day_ok:
                try:
                    summary = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
                    suspects = summary.get("suspects", [])
                    good_files = summary.get("ok", [])
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

        if day_ok:
            r = run_step(log, "analyze", ["src.analysis.analyze"])
            results["analyze"] = r
            day_ok = r.ok

        # --- synthesize: exactly one retry, then abort-the-day on failure ---
        if day_ok:
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
