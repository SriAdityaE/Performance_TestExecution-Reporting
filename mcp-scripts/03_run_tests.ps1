# =============================================================================
# 03_run_tests.ps1 — Run the full test suite
# Run this after any code change to verify nothing is broken.
# Pass -Coverage to also generate an HTML coverage report.
# =============================================================================

param(
    [switch]$Coverage,
    [string]$Module = ""   # Optional: test a single module e.g. "test_jtl_parser"
)

$ROOT        = Split-Path -Parent $PSScriptRoot
$VENV_PYTHON = "$ROOT\.venv\Scripts\python.exe"
$TESTS_DIR   = "$ROOT\mcp-server\tests"
$SRC_DIR     = "$ROOT\mcp-server\src\perf_mcp"

if (-not (Test-Path $VENV_PYTHON)) {
    Write-Error "Python venv not found. Run: cd mcp-server ; uv sync"
    exit 1
}

Set-Location "$ROOT\mcp-server"

$args = @("tests/")

if ($Module) {
    $args = @("tests/test_$Module.py", "-v")
    Write-Host "Running module: test_$Module.py" -ForegroundColor Cyan
} elseif ($Coverage) {
    $args = @("tests/", "--cov=src/perf_mcp", "--cov-report=html", "--cov-report=term-missing", "-q")
    Write-Host "Running full suite with coverage..." -ForegroundColor Cyan
} else {
    $args = @("tests/", "-q")
    Write-Host "Running full test suite..." -ForegroundColor Cyan
}

Write-Host ""
& $VENV_PYTHON -m pytest @args

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "[PASS] All tests passed." -ForegroundColor Green
    if ($Coverage) {
        Write-Host "[INFO] Coverage report: $ROOT\mcp-server\htmlcov\index.html" -ForegroundColor Cyan
        Start-Process "$ROOT\mcp-server\htmlcov\index.html"
    }
} else {
    Write-Host ""
    Write-Host "[FAIL] One or more tests failed. See output above." -ForegroundColor Red
    exit 1
}
