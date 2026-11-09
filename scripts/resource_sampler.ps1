# Resource sampler for the daily run (PROJECT_LOG 4.134): a SEPARATE process that never touches the pipeline.
# Every -IntervalSeconds it records system CPU, disk activity, the 5 busiest processes and OneDrive.exe, to files OUTSIDE
# the repository (default C:\geopolitics-experiments\resource_sampler). It stops when the day's run log says
# "daily_autorun.py finished for <date>", or after -MaxHours. A failure here is swallowed per sample and never
# reaches the pipeline (no shared state, no imports, read-only on the system).
#   powershell -NoProfile -File scripts\resource_sampler.ps1 [-Date 2026-11-10] [-IntervalSeconds 30] [-MaxHours 5]
param(
    [string]$Date = (Get-Date -Format 'yyyy-MM-dd'),
    [int]$IntervalSeconds = 30,
    [double]$MaxHours = 5,
    [string]$OutDir = 'C:\geopolitics-experiments\resource_sampler'
)
$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent $PSScriptRoot
$runLog = Join-Path $repo "automation_state\logs\$Date.log"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$sys = Join-Path $OutDir "system_$Date.csv"
$top = Join-Path $OutDir "top5_$Date.csv"
if (-not (Test-Path $sys)) { 'time,cpu_total_pct,disk_pct_busy,disk_bytes_per_sec,disk_queue,onedrive_cpu_pct,onedrive_ws_mb,onedrive_io_bytes_per_sec,ac_line,pipeline_stage' | Set-Content $sys -Encoding utf8 }
if (-not (Test-Path $top)) { 'time,rank,process,pid,cpu_pct_of_one_core' | Set-Content $top -Encoding utf8 }

function Get-Stage {
    # last "START <step>" line of today's run log, or '' before the run starts / after it ends
    try {
        if (-not (Test-Path $runLog)) { return '' }
        $lines = Get-Content $runLog -Tail 40 -ErrorAction Stop
        if ($lines | Where-Object { $_ -match 'daily_autorun\.py finished for' }) { return 'finished' }
        $m = $lines | Where-Object { $_ -match '\] START (\w+)' } | Select-Object -Last 1
        if ($m -match '\] START (\w+)') { return $Matches[1] }
    } catch { }
    return ''
}

$deadline = (Get-Date).AddHours($MaxHours)
$sawStart = $false
while ((Get-Date) -lt $deadline) {
    $t = Get-Date -Format 'yyyy-MM-ddTHH:mm:ss'
    try {
        $cpu = (Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor -Filter "Name='_Total'").PercentProcessorTime
        $d = Get-CimInstance Win32_PerfFormattedData_PerfDisk_PhysicalDisk -Filter "Name='_Total'"
        $procs = Get-CimInstance Win32_PerfFormattedData_PerfProc_Process |
            Where-Object { $_.Name -ne '_Total' -and $_.Name -ne 'Idle' }
        $od = $procs | Where-Object { $_.Name -like 'OneDrive*' } | Select-Object -First 1
        $odWs = if ($od) { [math]::Round($od.WorkingSet / 1MB, 1) } else { '' }
        $odIo = if ($od) { $od.IODataBytesPerSec } else { '' }
        $odCpu = if ($od) { $od.PercentProcessorTime } else { '' }
        $ac = try { (Get-CimInstance Win32_Battery -ErrorAction Stop | Select-Object -First 1).BatteryStatus } catch { '' }
        $stage = Get-Stage
        "$t,$cpu,$($d.PercentDiskTime),$($d.DiskBytesPerSec),$($d.CurrentDiskQueueLength),$odCpu,$odWs,$odIo,$ac,$stage" | Add-Content $sys -Encoding utf8
        $rank = 0
        foreach ($p in ($procs | Sort-Object PercentProcessorTime -Descending | Select-Object -First 5)) {
            $rank++
            "$t,$rank,$($p.Name),$($p.IDProcess),$($p.PercentProcessorTime)" | Add-Content $top -Encoding utf8
        }
        if ($stage -ne '' -and $stage -ne 'finished') { $sawStart = $true }
        if ($stage -eq 'finished') { break }
    } catch {
        "$t,ERROR,$($_.Exception.Message)" | Add-Content (Join-Path $OutDir "errors_$Date.txt") -Encoding utf8
    }
    Start-Sleep -Seconds $IntervalSeconds
}
