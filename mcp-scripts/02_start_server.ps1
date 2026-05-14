# =============================================================================
# 02_start_server.ps1 — Start the MCP server manually
#
# YOU DO NOT NEED THIS SCRIPT when using VS Code + GitHub Copilot.
# VS Code starts the server automatically via settings.json.
#
# Use this script ONLY when:
#   - Running the server standalone (outside VS Code)
#   - Debugging server startup issues
#   - Running the server directly on the VM (where L:\ is mounted)
# =============================================================================

$ROOT        = Split-Path -Parent $PSScriptRoot
$VENV_PYTHON = "$ROOT\.venv\Scripts\python.exe"
$MCP_SERVER  = "$ROOT\mcp-server\src"

if (-not (Test-Path $VENV_PYTHON)) {
    Write-Error "Python venv not found. Run: cd mcp-server ; uv sync"
    exit 1
}

Write-Host ""
Write-Host "Starting MCP server..." -ForegroundColor Cyan
Write-Host "  Python : $VENV_PYTHON" -ForegroundColor Gray
Write-Host "  Module : perf_mcp.server" -ForegroundColor Gray
Write-Host ""
Write-Host "The server listens on stdio and will stay running." -ForegroundColor Yellow
Write-Host "VS Code connects to it automatically via settings.json." -ForegroundColor Yellow
Write-Host "Press Ctrl+C to stop." -ForegroundColor Yellow
Write-Host ""

Set-Location "$ROOT\mcp-server"
& $VENV_PYTHON -m perf_mcp.server
