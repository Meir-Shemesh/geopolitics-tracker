<#
One-time setup script for scripts/daily_autorun.py's unattended daily run.
Run this yourself, directly in your own PowerShell window (not through an
automated tool) - the -RP * flag below makes Windows prompt YOU, securely,
for your Windows login password at the console. That prompt cannot be
scripted or piped from anywhere else, on purpose: this is the one place your
account password is ever entered for this whole setup, and it goes straight
to Task Scheduler's credential store, never through this script's own text.

Fires daily at 15:00 *local* (Israel) time, including through DST changes:
schtasks' /ST time is stored and evaluated in local wall-clock time by
Windows itself, so no manual UTC offset math is needed or wanted here.

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
#>

$TaskName = "GeopoliticsTrackerDailyAutorun"
$ProjectRoot = "C:\Users\meir\OneDrive\Documents\Claude Projects\geopolitics-tracker"
$PythonExe = Join-Path $ProjectRoot "venv\Scripts\python.exe"
$ScriptArgs = "-m scripts.daily_autorun"

if (-not (Test-Path $PythonExe)) {
    Write-Error "venv python not found at $PythonExe - check ProjectRoot/venv before continuing."
    exit 1
}

# \" (backslash-quote) around just the executable path - this is what schtasks.exe's
# own internal parser needs to see, once cmd.exe has handed it the full argument.
# /TR's value has internal structure (quoted-path THEN trailing args), which is why
# it alone needs this - see the file-level comment above for why /RU does not.
$TrValue = "\`"$PythonExe\`" $ScriptArgs"

# Plain quote-wrap only - no backslash-escaping - and the fully-qualified
# COMPUTERNAME\USERNAME form, more robust than a bare name for a local account.
$RunAsUser = "$env:COMPUTERNAME\$env:USERNAME"

$FullCommandLine = "schtasks /Create /TN `"$TaskName`" /TR `"$TrValue`" /SC DAILY /ST 15:00 " +
                    "/RU `"$RunAsUser`" /RP * /RL LIMITED /F"

# Quote-marked preview: every literal " becomes <Q>, every literal \ becomes <B> -
# makes it easy to visually confirm no stray quote/backslash characters ended up
# INSIDE a value (like the /RU bug this script just had) versus correctly marking
# an argument's own boundaries.
$MarkedPreview = $FullCommandLine.Replace('"', '<Q>').Replace('\', '<B>')

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
    Write-Output "Task '$TaskName' registered: fires daily at 15:00 local time, runs whether logged on or not."
    Write-Output ""
    Write-Output "Verify: schtasks /Query /TN `"$TaskName`" /V /FO LIST"
    Write-Output "Disable without deleting: schtasks /Change /TN `"$TaskName`" /Disable"
    Write-Output "Delete entirely: schtasks /Delete /TN `"$TaskName`" /F"
} else {
    Write-Error "schtasks /Create failed (exit $LASTEXITCODE) - see the error above."
}
