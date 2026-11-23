# Resource sampler for the daily run (PROJECT_LOG 4.134): a SEPARATE process that never touches the pipeline.
# Every -IntervalSeconds it records system CPU, disk activity, the 5 busiest processes and OneDrive.exe, to files OUTSIDE
# the repository (default C:\geopolitics-experiments\resource_sampler). It stops when the day's run log says
# "finished for <date>: success", or ": failure" with no new run within -FailureGraceMinutes (10), or after -MaxHours. A failure here is swallowed per sample and never
# reaches the pipeline (no shared state, no imports, read-only on the system).
#   powershell -NoProfile -File scripts\resource_sampler.ps1 [-Date 2026-11-10] [-IntervalSeconds 30] [-MaxHours 6]
param(
    [string]$Date = (Get-Date -Format 'yyyy-MM-dd'),
    [int]$IntervalSeconds = 30,
    [double]$MaxHours = 6,
    [double]$FailureGraceMinutes = 10,
    [string]$OutDir = 'C:\geopolitics-experiments\resource_sampler'
)
$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent $PSScriptRoot
$runLog = Join-Path $repo "automation_state\logs\$Date.log"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$sys = Join-Path $OutDir "system_$Date.csv"
$top = Join-Path $OutDir "top5_$Date.csv"
if (-not (Test-Path $sys)) { 'time,cpu_total_pct,disk_pct_busy,disk_bytes_per_sec,disk_queue,onedrive_cpu_pct,onedrive_ws_mb,onedrive_io_bytes_per_sec,ac_line,pipeline_stage,mem_available_mb,mem_committed_pct,pages_per_sec,pages_input_per_sec' | Set-Content $sys -Encoding utf8 }
if (-not (Test-Path $top)) { 'time,rank,process,pid,cpu_pct_of_one_core' | Set-Content $top -Encoding utf8 }

# Run state from today's run log. The log is appended to by every run of the day (a failed run can be followed by a rerun),
# so only the LAST "starting" and the LAST "finished" line decide: finished after the last start = the day's run is over
# (success or failure); a start after the last finish = a new run is going. Returns Stage ('' before any run,
# the last START step while running, 'finished:success' / 'finished:failure' when over) and FinishedAt.
function Get-RunState {
    $state = [pscustomobject]@{ Stage = ''; FinishedAt = $null }
    try {
        if (-not (Test-Path $runLog)) { return $state }
        $lines = @(Get-Content $runLog -ErrorAction Stop)
        $lastStart = -1; $lastFinish = -1; $lastStep = ''
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match 'daily_autorun\.py starting') { $lastStart = $i; $lastStep = '' }
            elseif ($lines[$i] -match '\] START (\w+)') { $lastStep = $Matches[1] }
            if ($lines[$i] -match 'daily_autorun\.py finished for [0-9-]+: (\w+)') { $lastFinish = $i }
        }
        if ($lastFinish -ge 0 -and $lastFinish -gt $lastStart) {
            $null = $lines[$lastFinish] -match '^\[([0-9T:-]+)\].*finished for [0-9-]+: (\w+)'
            $state.Stage = "finished:$($Matches[2])"
            $state.FinishedAt = [datetime]::ParseExact($Matches[1], 'yyyy-MM-ddTHH:mm:ss', $null)
        } elseif ($lastStart -ge 0) {
            $state.Stage = if ($lastStep) { $lastStep } else { 'starting' }
        }
    } catch { }
    return $state
}

# Memory counters, created once. The first NextValue() of a rate counter is meaningless, so each is read once here to prime it.
# If they cannot be created the four memory columns stay empty; nothing else is affected.
$memCounters = $null
try {
    $memCounters = [pscustomobject]@{
        Avail   = New-Object System.Diagnostics.PerformanceCounter('Memory', 'Available MBytes')
        Commit  = New-Object System.Diagnostics.PerformanceCounter('Memory', '% Committed Bytes In Use')
        Pages   = New-Object System.Diagnostics.PerformanceCounter('Memory', 'Pages/sec')
        PagesIn = New-Object System.Diagnostics.PerformanceCounter('Memory', 'Pages Input/sec')
    }
    foreach ($c in $memCounters.PSObject.Properties) { $null = $c.Value.NextValue() }
} catch { $memCounters = $null }

$deadline = (Get-Date).AddHours($MaxHours)
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
        $run = Get-RunState
        $stage = $run.Stage
        # Memory (added 2026-11-18 after the 15:00 unittest stall: Memory Compression was busy and nothing recorded memory).
        # Appended AFTER pipeline_stage so every existing column keeps its position; a failed read leaves the cells empty.
        # Read through four PerformanceCounter objects created once before the loop (about 3.5 ms for all four), not through
        # Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory (about 740 ms per sample, the costliest query of the sampler, measured
        # 2026-11-19: it kept WmiPrvSE busy on the day of the slow 15:00 run). Pages/sec is now the average rate since the previous
        # sample (about 30 s), not a one-second WMI snapshot, so those two columns are smoother than the ones recorded on 19.11.
        $memAvail = ''; $memCommit = ''; $pagesSec = ''; $pagesIn = ''
        try {
            if ($memCounters) {
                $memAvail = [math]::Round($memCounters.Avail.NextValue())
                $memCommit = [math]::Round($memCounters.Commit.NextValue())
                $pagesSec = [math]::Round($memCounters.Pages.NextValue())
                $pagesIn = [math]::Round($memCounters.PagesIn.NextValue())
            }
        } catch { $memAvail = ''; $memCommit = ''; $pagesSec = ''; $pagesIn = '' }
        "$t,$cpu,$($d.PercentDiskTime),$($d.DiskBytesPerSec),$($d.CurrentDiskQueueLength),$odCpu,$odWs,$odIo,$ac,$stage,$memAvail,$memCommit,$pagesSec,$pagesIn" | Add-Content $sys -Encoding utf8
        $rank = 0
        foreach ($p in ($procs | Sort-Object PercentProcessorTime -Descending | Select-Object -First 5)) {
            $rank++
            "$t,$rank,$($p.Name),$($p.IDProcess),$($p.PercentProcessorTime)" | Add-Content $top -Encoding utf8
        }
        # stop on 'finished: success', or on 'finished: failure' once 10 minutes pass without a new run starting
        if ($stage -eq 'finished:success') { break }
        if ($stage -eq 'finished:failure' -and ((Get-Date) - $run.FinishedAt).TotalMinutes -ge $FailureGraceMinutes) { break }
    } catch {
        "$t,ERROR,$($_.Exception.Message)" | Add-Content (Join-Path $OutDir "errors_$Date.txt") -Encoding utf8
    }
    Start-Sleep -Seconds $IntervalSeconds
}
