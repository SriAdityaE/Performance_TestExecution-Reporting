# Start the Performance MCP Server
# Usage: .\start_mcp_server.ps1

Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force

$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "❌ ERROR: .venv not found at $root\.venv" -ForegroundColor Red
    Write-Host "   Run: python -m venv .venv && .venv\Scripts\pip install -e mcp-server" -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ Starting perf-mcp server..." -ForegroundColor Green
Write-Host "   Python : $python" -ForegroundColor Cyan
Write-Host "   Press Ctrl+C to stop" -ForegroundColor Cyan
Write-Host ""

Set-Location $root
& $python -m perf_mcp.server
