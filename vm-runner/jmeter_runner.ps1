<#
.SYNOPSIS
    JMeter test runner daemon for remote VM execution.

.DESCRIPTION
    Polls the __QUEUE__ folder on the UNC shared path for new job files.
    On job pickup: moves job to __RUNNING__, executes JMeter in non-GUI mode,
    writes runner_live.log for live MCP tailing, writes heartbeat.json every
    60 seconds, and writes metadata.json + summary.json on completion.

    Start this script ONCE per session by RDP-ing into the VM and running:
        powershell -ExecutionPolicy RemoteSigned -File jmeter_runner.ps1

    It keeps the Command Prompt window open so JMeter output is visible.
    After test completion it waits 60 minutes for the next job before shutdown.

    SECURITY: No credentials in this file. All paths are read from job JSON.
    NEVER run this script with -NoProfile or in a hidden window.

.NOTES
    FR-009: All VM runner requirements (FR-009-1 through FR-009-10)
    Author: Nagarro Performance Engineering
    Version: 1.0
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Import-EnvFile {
    <#
    .SYNOPSIS
        Loads KEY=VALUE pairs from a .env file into process environment variables.
    .PARAMETER EnvPath
        Full path to the .env file.
    #>
    param([string]$EnvPath)

    if (-not (Test-Path $EnvPath)) {
        return
    }

    Get-Content -Path $EnvPath -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            return
        }

        $idx = $line.IndexOf("=")
        if ($idx -lt 1) {
            return
        }

        $key = $line.Substring(0, $idx).Trim()
        $value = $line.Substring($idx + 1).Trim()
        if (-not $key) {
            return
        }

        # Keep explicit process env precedence: only fill missing values.
        if (-not [Environment]::GetEnvironmentVariable($key, "Process")) {
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}

# Try known .env locations before reading required vars.
$RepoRoot = Split-Path -Parent $PSScriptRoot
Import-EnvFile -EnvPath (Join-Path $RepoRoot "mcp-server\.env")
Import-EnvFile -EnvPath (Join-Path $RepoRoot ".env")

# ---------------------------------------------------------------------------
# Configuration - ALL paths from environment or job JSON. Nothing hardcoded.
# ---------------------------------------------------------------------------

$JMETER_HOME         = if ($env:JMETER_HOME)         { $env:JMETER_HOME }         else { "C:\apache-jmeter" }
$SHARED_ROOT         = if ($env:PERF_SHARED_ROOT)     { $env:PERF_SHARED_ROOT }    else { throw "PERF_SHARED_ROOT env var is not set. Set it before running the runner." }
$QUEUE_DIR           = if ($env:JOB_QUEUE_DIR)        { $env:JOB_QUEUE_DIR }       else { "__QUEUE__" }
$RUNNING_DIR         = if ($env:JOB_RUNNING_DIR)      { $env:JOB_RUNNING_DIR }     else { "__RUNNING__" }
$COMPLETED_DIR       = if ($env:JOB_COMPLETED_DIR)    { $env:JOB_COMPLETED_DIR }   else { "__COMPLETED__" }
$POLL_INTERVAL_SEC   = if ($env:RUNNER_POLL_INTERVAL_SECONDS) { [int]$env:RUNNER_POLL_INTERVAL_SECONDS } else { 10 }
$IDLE_TIMEOUT_MIN    = if ($env:RUNNER_IDLE_TIMEOUT_MINUTES)  { [int]$env:RUNNER_IDLE_TIMEOUT_MINUTES }  else { 60 }

$QueuePath     = Join-Path $SHARED_ROOT $QUEUE_DIR
$RunningPath   = Join-Path $SHARED_ROOT $RUNNING_DIR
$CompletedPath = Join-Path $SHARED_ROOT $COMPLETED_DIR
$ResultsPath   = Join-Path $SHARED_ROOT "results"
$JMeterBin     = Join-Path $JMETER_HOME "bin\jmeter.bat"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

function Get-Timestamp {
    return (Get-Date -Format "HH:mm:ss")
}

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $line = "[$(Get-Timestamp)] [$Level] $Message"
    Write-Host $line
}

function Invoke-GitPull {
    <#
    .SYNOPSIS Pull latest jobs from GitHub. Non-fatal on failure.
    .PARAMETER RepoPath Root path of the git repository.
    #>
    param([string]$RepoPath)
    try {
        $out = & git -C $RepoPath pull --rebase 2>&1
        Write-Log "git pull: $out"
    } catch {
        Write-Log "WARNING: git pull failed (non-fatal): $_" "WARN"
    }
}

function Invoke-GitPush {
    <#
    .SYNOPSIS Stage all changes, commit, and push to GitHub. Non-fatal on failure.
    .PARAMETER RepoPath Root path of the git repository.
    .PARAMETER Message  Git commit message.
    #>
    param([string]$RepoPath, [string]$Message)
    try {
        & git -C $RepoPath add -A 2>&1 | Out-Null
        $commitOut = & git -C $RepoPath commit -m $Message 2>&1
        if ($LASTEXITCODE -eq 0) {
            $pushOut = & git -C $RepoPath push 2>&1
            Write-Log "git push: $pushOut"
        } else {
            Write-Log "git commit (nothing to commit or error): $commitOut"
        }
    } catch {
        Write-Log "WARNING: git push failed (non-fatal): $_" "WARN"
    }
}

function Write-Heartbeat {
    <#
    .SYNOPSIS Write heartbeat.json to the result folder every 60 seconds.
    .PARAMETER JobId Active job identifier.
    .PARAMETER ResultFolder Full path to result folder.
    .PARAMETER ElapsedSeconds Seconds since test start.
    .PARAMETER JMeterRunning Whether JMeter process is active.
    #>
    param(
        [string]$JobId,
        [string]$ResultFolder,
        [int]$ElapsedSeconds,
        [bool]$JMeterRunning
    )
    $heartbeat = @{
        job_id          = $JobId
        timestamp       = (Get-Date -Format "o")
        elapsed_seconds = $ElapsedSeconds
        jmeter_running  = $JMeterRunning
    } | ConvertTo-Json -Compress
    $heartbeatPath = Join-Path $ResultFolder "heartbeat.json"
    try {
        Set-Content -Path $heartbeatPath -Value $heartbeat -Encoding UTF8 -Force
    } catch {
        Write-Log "WARNING: Could not write heartbeat.json: $_" "WARN"
    }
}

function Write-Metadata {
    <#
    .SYNOPSIS Write or update metadata.json in the result folder.
    .PARAMETER Data Hashtable with metadata fields.
    .PARAMETER ResultFolder Full path to result folder.
    #>
    param([hashtable]$Data, [string]$ResultFolder)
    $metaPath = Join-Path $ResultFolder "metadata.json"
    try {
        $Data | ConvertTo-Json -Depth 5 | Set-Content -Path $metaPath -Encoding UTF8 -Force
    } catch {
        Write-Log "WARNING: Could not write metadata.json: $_" "WARN"
    }
}

function Write-Summary {
    <#
    .SYNOPSIS Write summary.json with parsed KPIs after test completion.
    Performs basic KPI extraction from the JTL file.
    .PARAMETER JtlPath Full path to the JTL CSV file.
    .PARAMETER ResultFolder Full path to result folder.
    .PARAMETER TestDurationSeconds Duration of the test in seconds.
    #>
    param([string]$JtlPath, [string]$ResultFolder, [double]$TestDurationSeconds)

    Write-Log "Parsing JTL for summary: $JtlPath"
    try {
        $rows = Import-Csv -Path $JtlPath -Encoding UTF8
        if (-not $rows -or $rows.Count -eq 0) {
            Write-Log "WARNING: JTL file is empty - no summary written" "WARN"
            return
        }

        $elapsed = $rows | ForEach-Object { [double]$_.elapsed }
        $totalRequests = $rows.Count
        $failed = ($rows | Where-Object { $_.success -ne "true" }).Count
        $successCount = $totalRequests - $failed

        # Sort elapsed for percentiles
        $sorted = $elapsed | Sort-Object

        function Get-Percentile([double[]]$Sorted, [double]$P) {
            $index = [Math]::Ceiling($P / 100.0 * $Sorted.Count) - 1
            $index = [Math]::Max(0, [Math]::Min($index, $Sorted.Count - 1))
            return $Sorted[$index]
        }

        $avgMs      = ($elapsed | Measure-Object -Average).Average
        $minMs      = ($elapsed | Measure-Object -Minimum).Minimum
        $maxMs      = ($elapsed | Measure-Object -Maximum).Maximum
        $p50        = Get-Percentile $sorted 50
        $p90        = Get-Percentile $sorted 90
        $p95        = Get-Percentile $sorted 95
        $p99        = Get-Percentile $sorted 99
        $errorRate  = if ($totalRequests -gt 0) { [Math]::Round(($failed / $totalRequests) * 100, 2) } else { 0 }
        $throughput = if ($TestDurationSeconds -gt 0) { [Math]::Round($totalRequests / $TestDurationSeconds, 2) } else { 0 }

        $totalBytes    = ($rows | ForEach-Object { [long]$_.bytes } | Measure-Object -Sum).Sum
        $totalSentBytes = ($rows | ForEach-Object { [long]$_.sentBytes } | Measure-Object -Sum).Sum
        $receivedKbSec = if ($TestDurationSeconds -gt 0) { [Math]::Round($totalBytes / 1024 / $TestDurationSeconds, 2) } else { 0 }
        $sentKbSec     = if ($TestDurationSeconds -gt 0) { [Math]::Round($totalSentBytes / 1024 / $TestDurationSeconds, 2) } else { 0 }

        $summary = @{
            total_requests     = $totalRequests
            successful_requests = $successCount
            failed_requests    = $failed
            error_rate_pct     = $errorRate
            avg_response_ms    = [Math]::Round($avgMs, 2)
            median_ms          = [Math]::Round($p50, 2)
            p90_ms             = [Math]::Round($p90, 2)
            p95_ms             = [Math]::Round($p95, 2)
            p99_ms             = [Math]::Round($p99, 2)
            min_ms             = [Math]::Round($minMs, 2)
            max_ms             = [Math]::Round($maxMs, 2)
            throughput_req_sec = $throughput
            received_kb_sec    = $receivedKbSec
            sent_kb_sec        = $sentKbSec
        }

        $summaryPath = Join-Path $ResultFolder "summary.json"
        $summary | ConvertTo-Json | Set-Content -Path $summaryPath -Encoding UTF8 -Force
        Write-Log "Summary written: $summaryPath | Requests: $totalRequests | Avg: $([Math]::Round($avgMs,0))ms | Errors: $errorRate%"

    } catch {
        Write-Log "ERROR: Failed to parse JTL for summary: $_" "ERROR"
    }
}

# ---------------------------------------------------------------------------
# Bootstrap: create required folders if missing
# ---------------------------------------------------------------------------

foreach ($dir in @($QueuePath, $RunningPath, $CompletedPath, $ResultsPath)) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Log "Created directory: $dir"
    }
}

Write-Log "============================================"
Write-Log "JMeter VM Runner started"
Write-Log "Shared root  : $SHARED_ROOT"
Write-Log "JMeter home  : $JMETER_HOME"
Write-Log "Poll interval: $POLL_INTERVAL_SEC s"
Write-Log "Idle timeout : $IDLE_TIMEOUT_MIN min"
Write-Log "============================================"

# Verify JMeter is installed
if (-not (Test-Path $JMeterBin)) {
    Write-Log "ERROR: JMeter not found at '$JMeterBin'. Set JMETER_HOME correctly." "ERROR"
    exit 1
}

# ---------------------------------------------------------------------------
# Main polling loop
# ---------------------------------------------------------------------------

$lastJobTime = Get-Date
$idleTimeoutSeconds = $IDLE_TIMEOUT_MIN * 60

while ($true) {

    # Idle timeout check (FR-009-8)
    $idleSeconds = (Get-Date) - $lastJobTime | Select-Object -ExpandProperty TotalSeconds
    if ($idleSeconds -ge $idleTimeoutSeconds) {
        Write-Log "Idle timeout reached ($IDLE_TIMEOUT_MIN min). Shutting down runner."
        break
    }

    # Pick up next job file from queue
    $jobFiles = Get-ChildItem -Path $QueuePath -Filter "*.json" -ErrorAction SilentlyContinue
    if (-not $jobFiles -or @($jobFiles).Count -eq 0) {
        Write-Log "No jobs in queue. Pulling from GitHub and waiting $POLL_INTERVAL_SEC s..."
        Invoke-GitPull -RepoPath $SHARED_ROOT
        Start-Sleep -Seconds $POLL_INTERVAL_SEC
        continue
    }

    # Process one job at a time (FR-009-9)
    $jobFile = $jobFiles | Sort-Object CreationTime | Select-Object -First 1
    $lastJobTime = Get-Date

    Write-Log "============================================"
    Write-Log "JOB PICKED UP: $($jobFile.Name)"

    # Parse job JSON
    try {
        $job = Get-Content -Path $jobFile.FullName -Encoding UTF8 | ConvertFrom-Json
    } catch {
        Write-Log "ERROR: Cannot parse job file '$($jobFile.Name)': $_" "ERROR"
        Remove-Item -Path $jobFile.FullName -Force -ErrorAction SilentlyContinue
        continue
    }

    $JobId        = $job.job_id
    $TestName     = $job.test_name
    $ScriptPath   = $job.script_path_on_vm
    $DayFolder    = $job.day_folder
    $ResultFolder = Join-Path $ResultsPath $DayFolder

    # Create result folder
    if (-not (Test-Path $ResultFolder)) {
        New-Item -ItemType Directory -Path $ResultFolder -Force | Out-Null
    }

    $JtlPath     = Join-Path $ResultFolder "$($TestName)_Round$($job.round).jtl"
    $LiveLogPath = Join-Path $ResultFolder "runner_live.log"

    # Move job from __QUEUE__ to __RUNNING__ (FR-009-3)
    $runningJobFile = Join-Path $RunningPath $jobFile.Name
    try {
        Move-Item -Path $jobFile.FullName -Destination $runningJobFile -Force
    } catch {
        Write-Log "ERROR: Cannot move job to __RUNNING__: $_" "ERROR"
        continue
    }

    # Write initial metadata.json (FR-009-6)
    $startedAt = (Get-Date -Format "o")
    Write-Metadata -ResultFolder $ResultFolder -Data @{
        job_id             = $JobId
        test_name          = $TestName
        script_path_on_vm  = $ScriptPath
        round              = $job.round
        day_folder         = $DayFolder
        status             = "running"
        started_at         = $startedAt
        completed_at       = $null
        error_message      = $null
    }

    # Push running status to GitHub so MCP server sees it immediately
    Invoke-GitPush -RepoPath $SHARED_ROOT -Message "running: $JobId"

    Write-Log "STARTING JMeter: $ScriptPath"
    Write-Log "Result folder  : $ResultFolder"
    Write-Log "JTL output     : $JtlPath"

    # ---------------------------------------------------------------------------
    # Execute JMeter (FR-009-4)
    # JMeter is launched as a background process so heartbeats can be written.
    # All output (stdout+stderr) is tee'd to runner_live.log for MCP live tailing.
    # ---------------------------------------------------------------------------
    $jmeterArgs = @(
        "-n",                         # Non-GUI mode
        "-t", "`"$ScriptPath`"",      # Test script path
        "-l", "`"$JtlPath`"",         # JTL output file
        "-e",                         # Generate HTML dashboard (optional, non-blocking)
        "-o", "`"$ResultFolder\dashboard`""  # Dashboard output folder
    )

    $jmeterArgString = $jmeterArgs -join " "
    Write-Log "JMeter command: $JMeterBin $jmeterArgString"

    # Start JMeter and capture PID for monitoring.
    # .bat files require cmd.exe as the host when UseShellExecute=false (output redirect).
    $processStartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $processStartInfo.FileName               = "cmd.exe"
    $processStartInfo.Arguments              = "/c `"$JMeterBin`" $jmeterArgString"
    $processStartInfo.RedirectStandardOutput = $true
    $processStartInfo.RedirectStandardError  = $true
    $processStartInfo.UseShellExecute        = $false
    $processStartInfo.CreateNoWindow         = $false   # Visible Command Prompt window (FR-009-7)

    $jmeterProcess = New-Object System.Diagnostics.Process
    $jmeterProcess.StartInfo = $processStartInfo

    # Append stdout to runner_live.log asynchronously (FR-009-10)
    $jmeterProcess.add_OutputDataReceived({
        param($sender, $e)
        if ($null -ne $e.Data -and $e.Data.Trim() -ne "") {
            $logLine = "[$(Get-Date -Format 'HH:mm:ss')] $($e.Data)"
            Add-Content -Path $LiveLogPath -Value $logLine -Encoding UTF8
            Write-Host $logLine   # Also show in Command Prompt (FR-009-7)
        }
    })
    $jmeterProcess.add_ErrorDataReceived({
        param($sender, $e)
        if ($null -ne $e.Data -and $e.Data.Trim() -ne "") {
            $logLine = "[$(Get-Date -Format 'HH:mm:ss')] [STDERR] $($e.Data)"
            Add-Content -Path $LiveLogPath -Value $logLine -Encoding UTF8
            Write-Host $logLine
        }
    })

    try {
        $jmeterProcess.Start() | Out-Null
        $jmeterProcess.BeginOutputReadLine()
        $jmeterProcess.BeginErrorReadLine()
    } catch {
        Write-Log "ERROR: Failed to start JMeter process: $_" "ERROR"
        Write-Metadata -ResultFolder $ResultFolder -Data @{
            job_id        = $JobId
            test_name     = $TestName
            script_path_on_vm = $ScriptPath
            round         = $job.round
            day_folder    = $DayFolder
            status        = "failed"
            started_at    = $startedAt
            completed_at  = (Get-Date -Format "o")
            error_message = "Failed to start JMeter: $_"
        }
        Move-Item -Path $runningJobFile -Destination (Join-Path $CompletedPath $jobFile.Name) -Force -ErrorAction SilentlyContinue
        continue
    }

    Write-Log "JMeter started. PID: $($jmeterProcess.Id)"

    # ---------------------------------------------------------------------------
    # Heartbeat loop while JMeter runs (FR-009-5)
    # ---------------------------------------------------------------------------
    $testStartTime = Get-Date
    $heartbeatInterval = 60  # seconds

    while (-not $jmeterProcess.HasExited) {
        Start-Sleep -Seconds $heartbeatInterval
        $elapsedSec = [int]((Get-Date) - $testStartTime).TotalSeconds
        Write-Heartbeat -JobId $JobId -ResultFolder $ResultFolder -ElapsedSeconds $elapsedSec -JMeterRunning $true
        Write-Log "HEARTBEAT - Elapsed: $([Math]::Floor($elapsedSec / 60)) min | JMeter running (PID $($jmeterProcess.Id))"
    }

    # Final heartbeat after exit
    $testEndTime = Get-Date
    $testDurationSeconds = ($testEndTime - $testStartTime).TotalSeconds
    Write-Heartbeat -JobId $JobId -ResultFolder $ResultFolder `
        -ElapsedSeconds ([int]$testDurationSeconds) -JMeterRunning $false

    $exitCode = $jmeterProcess.ExitCode
    Write-Log "JMeter exited with code: $exitCode | Duration: $([Math]::Round($testDurationSeconds, 1))s"

    # ---------------------------------------------------------------------------
    # Post-run: write metadata + summary (FR-009-6)
    # ---------------------------------------------------------------------------
    if ($exitCode -eq 0 -and (Test-Path $JtlPath)) {
        Write-Summary -JtlPath $JtlPath -ResultFolder $ResultFolder -TestDurationSeconds $testDurationSeconds

        Write-Metadata -ResultFolder $ResultFolder -Data @{
            job_id            = $JobId
            test_name         = $TestName
            script_path_on_vm = $ScriptPath
            round             = $job.round
            day_folder        = $DayFolder
            status            = "completed"
            started_at        = $startedAt
            completed_at      = (Get-Date -Format "o")
            error_message     = $null
        }
        Write-Log "JOB COMPLETED: $JobId"

    } else {
        $errMsg = if ($exitCode -ne 0) { "JMeter exited with code $exitCode" } else { "JTL file not found after run" }
        Write-Metadata -ResultFolder $ResultFolder -Data @{
            job_id            = $JobId
            test_name         = $TestName
            script_path_on_vm = $ScriptPath
            round             = $job.round
            day_folder        = $DayFolder
            status            = "failed"
            started_at        = $startedAt
            completed_at      = (Get-Date -Format "o")
            error_message     = $errMsg
        }
        Write-Log "JOB FAILED: $JobId | $errMsg" "ERROR"
    }

    # Move job file to __COMPLETED__
    Move-Item -Path $runningJobFile `
              -Destination (Join-Path $CompletedPath $jobFile.Name) `
              -Force -ErrorAction SilentlyContinue

    # Push final results to GitHub so MCP server can pull and generate report
    Invoke-GitPush -RepoPath $SHARED_ROOT -Message "completed: $JobId"

    Write-Log "============================================"
    Write-Log "Ready for next job. Polling every $POLL_INTERVAL_SEC s..."
    $lastJobTime = Get-Date
}

Write-Log "VM Runner shutdown complete."
