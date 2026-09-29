<#
One-time setup script for scripts/daily_autorun.py's unattended daily run.
Run this yourself, directly in your own PowerShell window (not through an
automated tool) - the -RP * flag below makes Windows prompt YOU, securely,
for your Windows login password at the console. That prompt cannot be
scripted or piped from anywhere else, on purpose: this is the one place your
account password is ever entered for this whole setup, and it goes straight
to Task Scheduler's credential store, never through this script's own text.

Fires daily at 15:00 *local* (Israel) time, including through DST changes:
New-ScheduledTaskTrigger's -Daily -At form is stored and evaluated in local
wall-clock time by Windows itself, so no manual UTC offset math is needed
or wanted here - the same 15:00 target applies whether the current offset
is +02:00 or +03:00.

"Run whether user is logged on or not" (so it keeps firing through a locked
screen or a logged-out session over a multi-day unattended stretch) requires
Task Scheduler to hold a stored password - that's what /RP * supplies below.
If you'd rather not store it, drop -RP * (and the /RU line) and register via
the Task Scheduler GUI's "Run only when user is logged on" option instead;
daily_autorun.py itself doesn't care which way the task is configured.
#>

$TaskName = "GeopoliticsTrackerDailyAutorun"
$ProjectRoot = "C:\Users\meir\OneDrive\Documents\Claude Projects\geopolitics-tracker"
$PythonExe = Join-Path $ProjectRoot "venv\Scripts\python.exe"
$ScriptArgs = "-m scripts.daily_autorun"

if (-not (Test-Path $PythonExe)) {
    Write-Error "venv python not found at $PythonExe - check ProjectRoot/venv before continuing."
    exit 1
}

schtasks /Create `
    /TN $TaskName `
    /TR "`"$PythonExe`" $ScriptArgs" `
    /SC DAILY `
    /ST 15:00 `
    /RU $env:USERNAME `
    /RP * `
    /RL LIMITED `
    /F

if ($LASTEXITCODE -eq 0) {
    Write-Output ""
    Write-Output "Task '$TaskName' registered: fires daily at 15:00 local time, runs whether logged on or not."
    Write-Output "Working directory for the task is set implicitly by the python.exe's own cwd handling inside"
    Write-Output "daily_autorun.py (it hardcodes PROJECT_ROOT), so no /st (start-in) directory is needed here."
    Write-Output ""
    Write-Output "Verify: schtasks /Query /TN `"$TaskName`" /V /FO LIST"
    Write-Output "Disable without deleting: schtasks /Change /TN `"$TaskName`" /Disable"
    Write-Output "Delete entirely: schtasks /Delete /TN `"$TaskName`" /F"
} else {
    Write-Error "schtasks /Create failed (exit $LASTEXITCODE) - see the error above."
}
