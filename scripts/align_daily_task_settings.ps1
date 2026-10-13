<#
One-time fix (2026-10-13, PROJECT_LOG 4.98): aligns GeopoliticsTrackerDailyAutorun's
power/wake settings with GeopoliticsTrackerBiweeklyAutorun:

  DisallowStartIfOnBatteries  true  -> false   (a laptop on battery at 15:00 skipped the day)
  StopIfGoingOnBatteries      true  -> false   (unplugging mid-run killed a ~1.5h run)
  WakeToRun                   false -> true
  StartWhenAvailable          false -> true     (a missed 15:00 start runs when the PC is back)

Why a script and not Set-ScheduledTask: this task is registered "run whether
logged on or not" (LogonType Password), and changing it needs the account
password - Set-ScheduledTask fails with "The user name or password is
incorrect" without it. This script exports the CURRENT task XML (so the action,
trigger and everything else are carried over untouched), patches only these four
elements, and re-registers it; Windows prompts for your password once.

-WhatIf only writes the patched XML next to this script's output and prints a
diff against the current task - nothing is registered.
#>
param([switch]$WhatIf)

$TaskName = "GeopoliticsTrackerDailyAutorun"
$Current = Join-Path $env:TEMP "daily_task_current.xml"
$Patched = Join-Path $env:TEMP "daily_task_patched.xml"

schtasks /Query /TN $TaskName /XML | Out-File -FilePath $Current -Encoding Unicode
[xml]$x = Get-Content -Raw -Path $Current
$ns = New-Object System.Xml.XmlNamespaceManager($x.NameTable)
$ns.AddNamespace("t", "http://schemas.microsoft.com/windows/2004/02/mit/task")
$settings = $x.SelectSingleNode("//t:Settings", $ns)

function Set-Element([string]$name, [string]$value) {
    $node = $settings.SelectSingleNode("t:$name", $ns)
    if (-not $node) {
        $node = $x.CreateElement($name, $ns.LookupNamespace("t"))
        [void]$settings.AppendChild($node)
    }
    $node.InnerText = $value
}
Set-Element "DisallowStartIfOnBatteries" "false"
Set-Element "StopIfGoingOnBatteries" "false"
Set-Element "WakeToRun" "true"
Set-Element "StartWhenAvailable" "true"
$x.Save($Patched)

Write-Host "--- settings before -> after ---"
Compare-Object (Get-Content $Current) (Get-Content $Patched) | Format-Table -AutoSize

if ($WhatIf) { Write-Host "WhatIf: nothing registered. Patched XML: $Patched"; return }

Write-Host "Windows will now prompt for YOUR account password." -ForegroundColor Cyan
cmd /c "schtasks /Create /TN `"$TaskName`" /XML `"$Patched`" /RU `"$env:USERNAME`" /RP * /F"
if ($LASTEXITCODE -eq 0) {
    Get-ScheduledTask -TaskName $TaskName | Select-Object -ExpandProperty Settings |
        Select-Object DisallowStartIfOnBatteries, StopIfGoingOnBatteries, WakeToRun, StartWhenAvailable, ExecutionTimeLimit |
        Format-List
    Get-ScheduledTaskInfo -TaskName $TaskName | Select-Object NextRunTime | Format-List
} else {
    Write-Error "schtasks /Create failed (exit $LASTEXITCODE) - the original task is unchanged."
}
