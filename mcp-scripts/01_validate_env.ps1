# =============================================================================
# 01_validate_env.ps1 - Pre-flight environment check
# Run this ONCE before starting a session to confirm everything is wired.
# No files are modified. Safe to run repeatedly.
# =============================================================================

$ROOT        = Split-Path -Parent $PSScriptRoot
$VENV_PYTHON = Join-Path $ROOT '.venv\Scripts\python.exe'
$ENV_FILE    = Join-Path $ROOT 'mcp-server\.env'

Write-Host ''
Write-Host '========================================' -ForegroundColor Cyan
Write-Host '  MCP Server - Pre-flight Check'         -ForegroundColor Cyan
Write-Host '========================================' -ForegroundColor Cyan
Write-Host ''

$allOk = $true

# 1. Python venv
if (Test-Path $VENV_PYTHON) {
    $pyVer = & $VENV_PYTHON --version 2>&1
    Write-Host ('[PASS] Python venv   : ' + $pyVer) -ForegroundColor Green
} else {
    Write-Host ('[FAIL] Python venv not found at ' + $VENV_PYTHON) -ForegroundColor Red
    Write-Host '       Fix: cd mcp-server then run: uv sync' -ForegroundColor Yellow
    $allOk = $false
}

# 2. .env file
if (Test-Path $ENV_FILE) {
    Write-Host '[PASS] .env file     : found' -ForegroundColor Green
} else {
    Write-Host ('[FAIL] .env file missing: ' + $ENV_FILE) -ForegroundColor Red
    Write-Host '       Create it from the template in RUNBOOK.md Phase 5' -ForegroundColor Yellow
    $allOk = $false
}

# 3. Key env vars (read without printing secrets)
$sharedRoot = ''
$channel    = ''
if (Test-Path $ENV_FILE) {
    $envContent = Get-Content $ENV_FILE
    $sharedRoot = ($envContent | Where-Object { $_ -match '^PERF_SHARED_ROOT=' }) -replace '^PERF_SHARED_ROOT=', ''
    $slackSet   = ($envContent | Where-Object { $_ -match '^SLACK_WEBHOOK_URL=https://' }).Count -gt 0
    $channel    = ($envContent | Where-Object { $_ -match '^NOTIFICATION_CHANNEL=' }) -replace '^NOTIFICATION_CHANNEL=', ''

    if ($sharedRoot) {
        Write-Host '[PASS] PERF_SHARED_ROOT  : set' -ForegroundColor Green
    } else {
        Write-Host '[FAIL] PERF_SHARED_ROOT not set in .env' -ForegroundColor Red
        $allOk = $false
    }

    if ($slackSet) {
        Write-Host '[PASS] SLACK_WEBHOOK_URL : set' -ForegroundColor Green
    } else {
        Write-Host '[WARN] SLACK_WEBHOOK_URL not set (Slack skipped)' -ForegroundColor Yellow
    }

    Write-Host ('[INFO] NOTIFICATION_CHANNEL = ' + $channel) -ForegroundColor Cyan
}

# 4. UNC share reachability
if ($sharedRoot -and $sharedRoot.StartsWith('\\')) {
    $reachable = Test-Path $sharedRoot -ErrorAction SilentlyContinue
    if ($reachable) {
        Write-Host ('[PASS] UNC share reachable: ' + $sharedRoot) -ForegroundColor Green
    } else {
        Write-Host ('[FAIL] UNC share NOT reachable: ' + $sharedRoot) -ForegroundColor Red
        Write-Host '       Ensure this machine is on the same network as the VM' -ForegroundColor Yellow
        Write-Host '       OR run the MCP server directly on the VM where L: is mounted' -ForegroundColor Yellow
        $allOk = $false
    }
}

# 5. MCP package importable
Push-Location (Join-Path $ROOT 'mcp-server')
$importCheck = & $VENV_PYTHON -m py_compile src\perf_mcp\server.py 2>&1
Pop-Location
if ($LASTEXITCODE -eq 0) {
    Write-Host '[PASS] perf_mcp      : importable' -ForegroundColor Green
} else {
    Write-Host ('[FAIL] perf_mcp compile error: ' + $importCheck) -ForegroundColor Red
    Write-Host '       Fix: cd mcp-server then run: uv sync' -ForegroundColor Yellow
    $allOk = $false
}

Write-Host ''
if ($allOk) {
    Write-Host '========================================' -ForegroundColor Green
    Write-Host '  ALL CHECKS PASSED - Ready to use'      -ForegroundColor Green
    Write-Host '========================================' -ForegroundColor Green
} else {
    Write-Host '========================================' -ForegroundColor Red
    Write-Host '  ONE OR MORE CHECKS FAILED - See above' -ForegroundColor Red
    Write-Host '========================================' -ForegroundColor Red
}
Write-Host ''
