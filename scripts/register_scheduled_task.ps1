<#
One-time setup script for scripts/daily_autorun.py's unattended daily run.
Run this yourself, directly in your own PowerShell window (not through an
automated tool) - the -RP * flag below makes Windows prompt YOU, securely,
for your Windows login password at the console. That prompt cannot be
scripted or piped from anywhere else, on purpose: this is the one place your
account password is ever entered for this whole setup, and it goes straight
to Task Scheduler's credential store, never through this script's own text.
It prompts twice (once per task registered below).

Fires daily at 15:00 *local* (Israel) time, including through DST changes:
schtasks' /ST time is stored and evaluated in local wall-clock time by
Windows itself, so no manual UTC offset math is needed or wanted here.

Registers FOUR scheduled tasks (added 2026-09-30, extended 2026-10-02 - see
PROJECT_LOG):
  1. GeopoliticsTrackerDailyAutorun (daily, 15:00) - runs
     scripts/run_daily_autorun_launcher.bat, which itself sends a "run
     started" email BEFORE attempting to launch daily_autorun.py, then
     launches it.
  2. GeopoliticsTrackerRunProgressCheck (daily, 15:10, ten minutes later) -
     a fully SEPARATE task, not depending on task 1's process in any way.
     Runs scripts/scheduler_notify.py check-progress, which looks for
     today's automation_state/logs/{date}.log and sends an alarm email if
     it's missing (daily_autorun.py's log_open() is one of the very first
     things it does, so a missing log 10 minutes in means it almost
     certainly crashed before doing anything meaningful).
  3. GeopoliticsAnalyticsWeeklyReport (weekly, Monday 08:00) - runs
     scripts/analytics_report.py --period weekly.
  4. GeopoliticsAnalyticsMonthlyReport (monthly, day 1, 08:00) - runs
     scripts/analytics_report.py --period monthly.
  Tasks 1-2's launcher .bat and scheduler_notify.py are deliberately
  independent of daily_autorun.py's own code/imports - see their own
  file-header comments for why (in short: 2026-09-30's real failure was a
  crash at Python's own import-resolution stage, before any of
  daily_autorun.py's code, including its own send_email(), had run).
  Tasks 3-4 (analytics_report.py) carry the same same-machine-must-be-on
  constraint as tasks 1-2 - an explicit, accepted tradeoff (see that
  script's own docstring) rather than adding a cloud-side email provider.

Quoting note (2026-09-30): schtasks.exe's /TR value needs to look like
`"<path with spaces>" <extra args>` - i.e. it needs its OWN embedded quotes
around just the executable path, on top of the whole thing needing quotes
because it contains spaces. PowerShell 5.1's native-command argument
marshalling does not reliably preserve embedded double-quotes when invoking
schtasks.exe directly (confirmed by hand: this exact project's path,
"...Claude Projects\geopolitics-tracker\...", reproduced the failure every
time - both a bare space-separated call and an array passed via the call
operator (&) or Start-Process -ArgumentList all mis-parsed it). The fix that
was empirically verified to work is building the whole command as one
literal string with CMD-style backslash-escaped quotes (\" around the
executable path specifically) and running it through cmd.exe /c - cmd's own
line parsing (not PowerShell's native-argument marshalling) is what actually
constructs schtasks.exe's command line in that case, and it handles this
correctly.

Second quoting note (same day, caught on the next run): /RU's value is a
FLAT username, not a "quoted-path + trailing args" string like /TR - it never
needed the backslash-escape trick above, only a plain quote-wrap (needed at
all only if the name itself contains a space). Applying /TR's \"..."\"
pattern to /RU by reflex put literal backslash+quote characters inside the
account-name value itself (schtasks then tried to resolve an account
literally called \"meir\", which of course doesn't exist - "No mapping
between account names and security IDs" is that exact symptom, a name-
resolution failure, not a Log-on-as-a-batch-job permission problem, which
would fail differently and later). Confirmed by hand: a plain real-quote wrap
around $env:COMPUTERNAME\$env:USERNAME (the fully-qualified local-account
form, more robust than a bare name) resolves correctly with no escaping at
all - that's what's used below.

Working-directory note (2026-09-30, found after the task's actual first live
15:00 fire failed with "Last Result: 1" and left no log file at all - meaning
it crashed before scripts/daily_autorun.py's own log_open() ever ran):
schtasks.exe's classic /Create flag set has NO way to set the task's "Start
In" working directory (confirmed: `schtasks /Query /V` on the already-created
task showed "Start In: N/A", with no flag above that could have set it). The
old /TR launched Python with `-m scripts.daily_autorun`, and `python -m`
resolves the target module against the process's OWN CURRENT WORKING
DIRECTORY (inserted as sys.path[0]) - not against the script's own location.
Task Scheduler's actual default working directory for a task with no "Start
In" is NOT the project folder, so `scripts` was never importable and Python
exited 1 with a bare ModuleNotFoundError traceback - before daily_autorun.py
had a chance to open its log or update state.json, which is exactly why both
were silently missing after the failed run. Reproduced by hand (safely - an
import-only check, not a real run): `python -c "import scripts.daily_autorun"`
from a directory other than the project root raises the identical
ModuleNotFoundError with exit code 1. Fixed by invoking every entry point by
its own full path instead of as a `-m` module (both here and inside the new
launcher .bat) - Path(__file__)-based PROJECT_ROOT inside daily_autorun.py,
and every subprocess call it makes, were already cwd-independent (each
explicitly passes cwd=PROJECT_ROOT) - only the outermost launch itself
depended on an assumed working directory that Task Scheduler never actually
provides.
#>

$ProjectRoot = "C:\Users\meir\OneDrive\Documents\Claude Projects\geopolitics-tracker"
$PythonExe = Join-Path $ProjectRoot "venv\Scripts\python.exe"
$LauncherBat = Join-Path $ProjectRoot "scripts\run_daily_autorun_launcher.bat"
$NotifyScript = Join-Path $ProjectRoot "scripts\scheduler_notify.py"
$AnalyticsReportScript = Join-Path $ProjectRoot "scripts\analytics_report.py"

foreach ($p in @($PythonExe, $LauncherBat, $NotifyScript, $AnalyticsReportScript)) {
    if (-not (Test-Path $p)) {
        Write-Error "Required file not found: $p - check ProjectRoot before continuing."
        exit 1
    }
}

# Plain quote-wrap only - no backslash-escaping - and the fully-qualified
# COMPUTERNAME\USERNAME form, more robust than a bare name for a local account.
$RunAsUser = "$env:COMPUTERNAME\$env:USERNAME"

function Register-OneTask {
    param(
        [string]$TaskName,
        [string]$TrValue,      # the exact value schtasks' /TR should receive (already \"-escaped if it needs it)
        [string]$ScheduleArgs  # e.g. "/SC DAILY /ST 15:00" or "/SC WEEKLY /D MON /ST 08:00"
    )

    $FullCommandLine = "schtasks /Create /TN `"$TaskName`" /TR `"$TrValue`" $ScheduleArgs " +
                        "/RU `"$RunAsUser`" /RP * /RL LIMITED /F"

    # Quote-marked preview: every literal " becomes <Q>, every literal \ becomes <B> -
    # makes it easy to visually confirm no stray quote/backslash characters ended up
    # INSIDE a value (like the /RU bug this script once had) versus correctly marking
    # an argument's own boundaries.
    $MarkedPreview = $FullCommandLine.Replace('"', '<Q>').Replace('\', '<B>')

    Write-Host "--- Registering '$TaskName' ($ScheduleArgs) ---" -ForegroundColor Cyan
    Write-Host "About to run the following command (review before it executes):" -ForegroundColor Cyan
    Write-Host $FullCommandLine -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Same line, with every literal `" marked <Q> and every literal \ marked <B> -" -ForegroundColor Cyan
    Write-Host "check that <Q> only appears at argument BOUNDARIES, never inside a plain value:" -ForegroundColor Cyan
    Write-Host $MarkedPreview -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Full command length: $($FullCommandLine.Length) characters" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Windows will now prompt you for YOUR account password (needed for 'run whether logged on or not')." -ForegroundColor Cyan
    Write-Host ""

    cmd /c $FullCommandLine

    if ($LASTEXITCODE -eq 0) {
        Write-Output ""
        Write-Output "Task '$TaskName' registered ($ScheduleArgs), runs whether logged on or not."
        Write-Output "Verify: schtasks /Query /TN `"$TaskName`" /V /FO LIST"
        Write-Output "Disable without deleting: schtasks /Change /TN `"$TaskName`" /Disable"
        Write-Output "Delete entirely: schtasks /Delete /TN `"$TaskName`" /F"
        Write-Output ""
        return $true
    } else {
        Write-Error "schtasks /Create failed for '$TaskName' (exit $LASTEXITCODE) - see the error above."
        return $false
    }
}

# --- Task 1: main run, via the launcher .bat (sends the "started" email,
# THEN runs daily_autorun.py - see the file header for why this two-step
# shape exists). \" escaping needed here (see the quoting note above) since
# the .bat path contains spaces.
$Tr1 = "\`"$LauncherBat\`""
$ok1 = Register-OneTask -TaskName "GeopoliticsTrackerDailyAutorun" -TrValue $Tr1 -ScheduleArgs "/SC DAILY /ST 15:00"

# --- Task 2: progress check, ten minutes later, fully independent of task 1.
$Tr2 = "\`"$PythonExe\`" \`"$NotifyScript\`" check-progress"
$ok2 = Register-OneTask -TaskName "GeopoliticsTrackerRunProgressCheck" -TrValue $Tr2 -ScheduleArgs "/SC DAILY /ST 15:10"

# --- Task 3: weekly analytics summary email, Monday mornings - matches
# analytics_report.py's own "7 days ending yesterday" window, so a Monday
# run summarizes the just-finished Mon-Sun week.
$Tr3 = "\`"$PythonExe\`" \`"$AnalyticsReportScript\`" --period weekly"
$ok3 = Register-OneTask -TaskName "GeopoliticsAnalyticsWeeklyReport" -TrValue $Tr3 -ScheduleArgs "/SC WEEKLY /D MON /ST 08:00"

# --- Task 4: monthly analytics summary email, the 1st of each month -
# matches analytics_report.py's own "previous full calendar month" window.
$Tr4 = "\`"$PythonExe\`" \`"$AnalyticsReportScript\`" --period monthly"
$ok4 = Register-OneTask -TaskName "GeopoliticsAnalyticsMonthlyReport" -TrValue $Tr4 -ScheduleArgs "/SC MONTHLY /D 1 /ST 08:00"

if ($ok1 -and $ok2 -and $ok3 -and $ok4) {
    Write-Output "All four tasks registered successfully."
} else {
    Write-Error "At least one task failed to register - see the errors above before relying on this."
}
