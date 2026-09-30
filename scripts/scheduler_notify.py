"""Standalone scheduler-notification helper - deliberately independent of
scripts/daily_autorun.py's own code and imports.

Why this has to be a SEPARATE file, not a function reused from
daily_autorun.py: 2026-09-30's real failure was a ModuleNotFoundError at
Python's own `-m` package-resolution stage - before a single line of
daily_autorun.py's code (including its own send_email()) had a chance to
run. Anything that imports daily_autorun.py, or anything under src/, would
have been just as unable to run at that moment. This file imports ONLY the
stdlib (smtplib/email/pathlib/etc.) - no python-dotenv, no project modules -
and is always invoked by its own full file path (never `-m`), exactly like
daily_autorun.py itself now is (see register_scheduled_task.ps1's
"Working-directory note"), so it cannot suffer the identical failure.

Two modes, run as two separate steps/tasks (see
scripts/run_daily_autorun_launcher.bat and register_scheduled_task.ps1):

    python scheduler_notify.py started
        Sent by the launcher BEFORE it even attempts to run daily_autorun.py.
        Proves Task Scheduler fired and the launcher itself is alive - NOT
        proof the pipeline is working.

    python scheduler_notify.py check-progress
        Run ~10 minutes later, by a SEPARATE scheduled task (does not depend
        on the main task's process in any way). Looks for the one signal
        that's both earliest and simplest to check: does today's
        automation_state/logs/{date}.log exist? daily_autorun.py's own
        log_open() is one of the very first things it does (right after
        load_env()) - if that file is missing 10 minutes in, the run almost
        certainly crashed before doing anything meaningful, and this sends
        its own alarm email.
"""
import smtplib
import subprocess
import sys
from datetime import date, datetime
from email.mime.text import MIMEText
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = PROJECT_ROOT / "automation_state"
LOG_DIR = STATE_DIR / "logs"
PAUSE_FLAG = PROJECT_ROOT / ".pause_automation"
SCHEDULED_TASK_NAME = "GeopoliticsTrackerDailyAutorun"


def load_env_minimal() -> dict:
    """Parses .env directly, line by line - deliberately NOT using
    python-dotenv, so this script's only dependency is the stdlib itself.
    Never prints or logs any value it reads (matches the project's standing
    rule: the Gmail app password must never appear in any output/log)."""
    env: dict[str, str] = {}
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return env
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def send_email(subject: str, body: str) -> bool:
    env = load_env_minimal()
    address = env.get("AUTOMATION_GMAIL_ADDRESS")
    app_password = env.get("AUTOMATION_GMAIL_APP_PASSWORD")
    to_address = env.get("AUTOMATION_ALERT_TO") or address or ""
    if not address or not app_password or not to_address:
        print(f"EMAIL NOT SENT (missing Gmail config in .env) - Subject: {subject}\n\n{body}")
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = address
    msg["To"] = to_address
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=60) as server:
            server.starttls()
            server.login(address, app_password)
            server.sendmail(address, [to_address], msg.as_string())
        return True
    except Exception as e:
        # Safe to print: SMTP exceptions never include the password itself.
        print(f"EMAIL SEND FAILED: {e!r}")
        return False


def cmd_started() -> int:
    today = date.today().isoformat()
    now = datetime.now().isoformat(timespec="seconds")
    ok = send_email(
        f"[Geopolitics Tracker] Scheduled run started - {today}",
        f"The scheduled task fired and this outer notifier ran at {now}.\n\n"
        f"This confirms Task Scheduler successfully launched something - it "
        f"does NOT yet confirm the pipeline itself is working. A separate "
        f"progress check runs about 10 minutes later. You should end up with "
        f"either:\n"
        f"  - this email + the normal run-summary email from daily_autorun.py "
        f"itself (healthy), or\n"
        f"  - this email + a 'stuck/crashed' alarm from the progress check "
        f"(something failed very early), or\n"
        f"  - neither email at all (check automation_state/logs/ and "
        f"schtasks /Query \"{SCHEDULED_TASK_NAME}\" by hand - this would mean "
        f"even this outer layer didn't run).\n",
    )
    print(f"started-notification email sent: {ok}")
    return 0


def is_task_disabled(task_name: str) -> bool | None:
    """Returns True if the named task is currently Disabled, False if
    Enabled, or None if this could not be determined (task not found,
    schtasks itself failed, etc.) - None is deliberately its own outcome,
    never silently treated as either True or False (see cmd_check_progress:
    an undetermined state falls through to the normal check rather than
    either suppressing or forcing an alarm on a guess)."""
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", task_name, "/V", "/FO", "LIST"],
            capture_output=True, text=True, timeout=30,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if line.startswith("Scheduled Task State:"):
            return line.split(":", 1)[1].strip() == "Disabled"
    return None


def cmd_check_progress() -> int:
    """Checks for evidence that today's run actually got going - but ONLY
    when the run was actually supposed to happen. A deliberate pause (either
    the main task Disabled via the GUI/schtasks, or .pause_automation
    present for just today) is NOT a failure and must never raise this
    alarm - added 2026-09-30 after the gap was caught before ever going
    live: the very first version of this check didn't look for either
    condition, so any intentional pause would have produced a false alarm
    every single day it was in effect."""
    today = date.today().isoformat()

    if PAUSE_FLAG.exists():
        print(f"Skipping: {PAUSE_FLAG.name} is present (today is intentionally paused) - no alarm.")
        return 0

    disabled = is_task_disabled(SCHEDULED_TASK_NAME)
    if disabled is True:
        print(f"Skipping: '{SCHEDULED_TASK_NAME}' is currently Disabled (intentionally paused) - no alarm.")
        return 0
    uncertainty_note = ""
    if disabled is None:
        # Could not confirm the task's Enabled/Disabled state (schtasks error,
        # task not found, etc.) - erring toward still checking rather than
        # silently trusting an unverified "it's probably paused" guess. If
        # this ends up alarming, the email says so explicitly rather than
        # presenting the log-file gap as the only story.
        print(f"Warning: could not determine whether '{SCHEDULED_TASK_NAME}' is Enabled/Disabled - "
              f"proceeding with the normal progress check anyway.")
        uncertainty_note = (
            f"\nNote: this check could also not confirm whether '{SCHEDULED_TASK_NAME}' is "
            f"currently Enabled or Disabled (the schtasks query itself failed or the task "
            f"was not found) - if it turns out to have been intentionally paused, this alarm "
            f"was a false positive caused by that, not by daily_autorun.py itself.\n"
        )

    log_path = LOG_DIR / f"{today}.log"
    if log_path.exists():
        print(f"Evidence of progress found ({log_path}) - no alarm needed.")
        return 0
    ok = send_email(
        f"[Geopolitics Tracker] ALARM: run may be stuck or crashed - {today}",
        f"The scheduled task fired today and a 'started' notification was "
        f"sent, but about 10 minutes later there is still no log file at:\n"
        f"  {log_path}\n\n"
        f"scripts/daily_autorun.py's own log_open() is one of the very first "
        f"things it does - its complete absence means the run almost "
        f"certainly crashed before daily_autorun.py itself executed "
        f"meaningfully (this is exactly the failure mode found on "
        f"2026-09-30: a ModuleNotFoundError from an outdated launch method, "
        f"since fixed - this check exists in case a *different* early-stage "
        f"failure happens in the future).\n"
        f"{uncertainty_note}\n"
        f"Check Task Scheduler's own record by hand:\n"
        f"  schtasks /Query /TN \"{SCHEDULED_TASK_NAME}\" /V /FO LIST\n",
    )
    print(f"stuck/crashed alarm email sent: {ok}")
    return 0


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ("started", "check-progress"):
        print("Usage: python scheduler_notify.py [started|check-progress]")
        return 2
    if sys.argv[1] == "started":
        return cmd_started()
    return cmd_check_progress()


if __name__ == "__main__":
    sys.exit(main())
