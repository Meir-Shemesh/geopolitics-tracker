<#
Registers ONE scheduled task - GeopoliticsTrackerBiweeklyAutorun - and touches
none of the four that scripts/register_scheduled_task.ps1 owns.

Run it yourself, in your own PowerShell window: Windows prompts once for your
login password ("run whether logged on or not"), exactly like the other tasks.

    powershell -ExecutionPolicy Bypass -File scripts\register_biweekly_task.ps1

What it sets up:
  - Fires every Thursday at 01:30 local time and runs
    scripts\run_biweekly_autorun_launcher.bat. The script behind it does real
    work only on the Thursday after a period's closing Wednesday and exits
    quietly on the other weeks - so the report is produced once every two
    weeks without the schedule itself having to know which week is which.
    (A true every-2-weeks trigger counts from its start date; register it on
    the wrong week and it would fire only on the off weeks, forever, with no
    error. A weekly trigger cannot get out of phase.)
  - 01:30 local wall-clock time, DST-safe the same way the 15:00 task is.
    Israel changes its clocks on a Friday (March) and a Sunday (October),
    never on a Thursday, so 01:30 is never a skipped or repeated time.
  - WakeToRun: wakes the machine from sleep for it (needs "Allow wake timers"
    enabled in the active power plan; does nothing if the machine is shut
    down or hibernated on some hardware).
  - StartWhenAvailable: if 01:30 was missed anyway, runs as soon as the
    machine is next up - Thursday morning rather than never.

This is built from task XML rather than schtasks' /SC flags because the two
settings above have no /Create flag.

-ValidateOnly registers a throwaway copy that needs no password
(interactive-only), launches it once through Task Scheduler, reads back its
result and deletes it. On any day that isn't the Thursday after a closing
Wednesday the launched script finds nothing due, so this proves the launch
path works without producing a report (see automation_state\logs\biweekly_*.log).
#>
param([switch]$ValidateOnly)

$ProjectRoot = "C:\Users\meir\OneDrive\Documents\Claude Projects\geopolitics-tracker"
$LauncherBat = Join-Path $ProjectRoot "scripts\run_biweekly_autorun_launcher.bat"
$TaskName = "GeopoliticsTrackerBiweeklyAutorun"
$RunAsUser = "$env:COMPUTERNAME\$env:USERNAME"

if (-not (Test-Path $LauncherBat)) {
    Write-Error "Required file not found: $LauncherBat - check ProjectRoot before continuing."
    exit 1
}

function New-TaskXml {
    param([string]$LogonType, [string]$Enabled)
    $escapedBat = [System.Security.SecurityElement]::Escape($LauncherBat)
    $escapedUser = [System.Security.SecurityElement]::Escape($RunAsUser)
    return @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>geopolitics-tracker: overnight biweekly trends report (scripts/biweekly_autorun.py). Fires every Thursday 01:30; does real work only after a period's closing Wednesday.</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-10-15T01:30:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek>
        <DaysOfWeek><Thursday /></DaysOfWeek>
        <WeeksInterval>1</WeeksInterval>
      </ScheduleByWeek>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$escapedUser</UserId>
      <LogonType>$LogonType</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>$Enabled</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$escapedBat</Command>
    </Exec>
  </Actions>
</Task>
"@
}

$XmlPath = Join-Path $env:TEMP "geopolitics_biweekly_task.xml"

if ($ValidateOnly) {
    $CheckName = "${TaskName}_xmlcheck"
    New-TaskXml -LogonType "InteractiveToken" -Enabled "true" | Out-File -FilePath $XmlPath -Encoding Unicode
    schtasks /Create /TN $CheckName /XML $XmlPath /F
    if ($LASTEXITCODE -ne 0) { Write-Error "Task XML was rejected."; exit 1 }
    # Launch it once through Task Scheduler itself - the launcher path has a
    # space in it and Task Scheduler does not start in the project folder,
    # which is exactly what broke the daily task's first live run.
    schtasks /Run /TN $CheckName
    Start-Sleep -Seconds 15
    schtasks /Query /TN $CheckName /V /FO LIST | Select-String "TaskName|Last Run Time|Last Result|Task To Run|Schedule Type|Start Time|Days"
    schtasks /Delete /TN $CheckName /F
    Remove-Item $XmlPath -ErrorAction SilentlyContinue
    exit 0
}

New-TaskXml -LogonType "Password" -Enabled "true" | Out-File -FilePath $XmlPath -Encoding Unicode

Write-Host "Registering '$TaskName' (every Thursday 01:30, wake-to-run, run-when-available)." -ForegroundColor Cyan
Write-Host "Windows will now prompt for YOUR account password." -ForegroundColor Cyan
cmd /c "schtasks /Create /TN `"$TaskName`" /XML `"$XmlPath`" /RU `"$RunAsUser`" /RP * /F"
$created = $LASTEXITCODE
Remove-Item $XmlPath -ErrorAction SilentlyContinue

if ($created -eq 0) {
    Write-Output ""
    Write-Output "Task '$TaskName' registered."
    Write-Output "Verify:        schtasks /Query /TN `"$TaskName`" /V /FO LIST"
    Write-Output "Test it now:   schtasks /Run /TN `"$TaskName`"   (then read automation_state\logs\biweekly_<today>.log)"
    Write-Output "Disable:       schtasks /Change /TN `"$TaskName`" /Disable"
    Write-Output "Delete:        schtasks /Delete /TN `"$TaskName`" /F"
} else {
    Write-Error "schtasks /Create failed for '$TaskName' (exit $created) - see the error above."
    exit 1
}
