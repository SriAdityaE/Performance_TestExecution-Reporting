# MCP Server Testing & Operations Runbook

**Last Updated:** April 29, 2026  
**Version:** 1.0.0  
**Purpose:** Step-by-step guide to start, test, and operate the Performance Test Execution MCP Server

---

## Quick Reference

| Task | Command | Time |
|------|---------|------|
| Setup (first time) | `.\setup.ps1` | 5-10 min |
| Start MCP Server | `.\.venv\Scripts\python.exe -m perf_mcp.server` | Immediate |
| Run All Tests | `.\.venv\Scripts\python.exe -m pytest mcp-server/tests/ -q` | 30 sec |
| Check Git Status | `git status` | Instant |

---

## Prerequisites

Before you start, verify you have:

✅ **Python 3.11+** installed  
✅ **uv** package manager installed (`pip install uv`)  
✅ **Git** installed and configured  
✅ **.venv** virtual environment in `mcp-server/.venv` (created by setup.ps1)  
✅ **GitHub repo cloned** locally

**Verify prerequisites:**

```powershell
# Check Python version
python --version

# Check uv is installed
uv --version

# Check git is installed
git --version

# Verify .venv exists
ls mcp-server\.venv\Scripts\python.exe
```

---

## Phase 1: Initial Setup (First Time Only)

### Step 1.1: Clone Repository

```powershell
cd "C:\Users\erraguntlaaditya\OneDrive - Nagarro\Documents\Practice\MCPServer"

git clone https://github.com/SriAdityaE/Performance_TestExecution-Reporting.git

cd Performance_TestExecution-Reporting
```

**Expected output:**
```
Cloning into 'Performance_TestExecution-Reporting'...
remote: Enumerating objects: 31, done.
...
```

---

### Step 1.2: Run Setup Script (One Time)

```powershell
.\setup.ps1
```

**What it does:**
- Creates `.venv` virtual environment
- Installs Python dependencies (pydantic, mcp, pandas, jinja2, pytest, requests)
- Installs package in editable mode

**Expected output:**
```
✅ Virtual environment created
✅ Dependencies installed
✅ Package installed in editable mode
```

**Troubleshooting:**
- If PowerShell execution policy blocks the script:
  ```powershell
  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
  .\setup.ps1
  ```

---

## Phase 2: Start MCP Server

### Step 2.1: Activate Virtual Environment

```powershell
# Navigate to project root
cd "C:\Users\erraguntlaaditya\OneDrive - Nagarro\Documents\Practice\MCPServer\Performance_TestExecution&Reporting"

# Activate the virtual environment
.\.venv\Scripts\Activate.ps1
```

**Expected output:**
```
(.venv) PS C:\Users\...\Performance_TestExecution&Reporting>
```

Note: The `(.venv)` prefix confirms the virtual environment is active.

---

### Step 2.2: Start MCP Server

```powershell
.\.venv\Scripts\python.exe -m perf_mcp.server
```

**Expected output:**
```
[HH:MM:SS] 🚀 MCP STARTED — Waiting for MCP client to connect
```

**The server will stay running.** It is waiting for stdio MCP client messages.

**On first tool request from a client, you will see:**
```
[HH:MM:SS] ✅ MCP CLIENT CONNECTED — First tool request received
```

---

### Step 2.3: Verify Server is Running

**In a NEW terminal tab/window:**

```powershell
# Verify the process is running
Get-Process | Where-Object { $_.ProcessName -like "*python*" }
```

**Expected output:**
```
Handles  NPM(K)    PM(K)      WS(K)     CPU(s)     Id  ProcessName
-------  ------    -----      -----     ------     --  -----------
   1234      567   123456     234567     0.12   5678  python.exe
```

---

## Phase 3: Test MCP Server

### Step 3.1: Run Unit Tests

```powershell
# From project root
.\.venv\Scripts\python.exe -m pytest mcp-server/tests/ -q
```

**Expected output:**
```
................................................................         [100%]
============================== warnings summary =======================================
tests/test_jtl_parser.py::TestParseJtlHappyPath::test_skipped_rows_counted
  C:\Users\...\jtl_parser.py:88: ParserWarning: Skipping line 6: expected 22 fields, saw 23
  
    df = pd.read_csv(

------ docs: https://docs.pytest.org/en/latest/how-this-warning-comes-from.html ------
64 passed, 1 warning in 3.30s
```

**Result:** ✅ **64 tests passed** (1 warning is expected and non-blocking)

---

### Step 3.2: Run Tests with Coverage

```powershell
# From project root
.\.venv\Scripts\python.exe -m pytest mcp-server/tests/ --cov=mcp-server/src/perf_mcp --cov-report=html -q
```

**Expected output:**
```
64 passed, 1 warning in 5.21s
Coverage report generated in htmlcov/index.html
```

**View coverage report:**
```powershell
# Windows
Start-Process htmlcov\index.html

# macOS/Linux
open htmlcov/index.html
```

---

### Step 3.3: Run Specific Test Module

```powershell
# From project root
# Test only JTL parser
.\.venv\Scripts\python.exe -m pytest mcp-server/tests/test_jtl_parser.py -v

# Test only notifier
.\.venv\Scripts\python.exe -m pytest mcp-server/tests/test_notifier.py -v

# Test only report generator
.\.venv\Scripts\python.exe -m pytest mcp-server/tests/test_report_generator.py -v

# Test only models
.\.venv\Scripts\python.exe -m pytest mcp-server/tests/test_models.py -v
```

**Expected output for each:**
```
tests/test_jtl_parser.py::TestParseJtlHappyPath::test_single_label PASSED [X%]
tests/test_jtl_parser.py::TestParseJtlHappyPath::test_multi_label PASSED [X%]
...
```

---

## Phase 4: Manual MCP Tool Testing

### Step 4.1: Test Tool 1 - start_test_execution

**Command:**
```powershell
# While MCP server is running, create a test job in another terminal

$job_request = @{
    test_name = "GET_RO_Number_Load"
    script_path_on_vm = "L:\Latest_Script_Sqlserver\Xinsepect_RDS_SQL&BabelfishTestplan_Latest_07_21.jmx"
    shared_root = "L:\Testlogfiles\MCP_Testlogfiles_entry"
    notification_channel = "terminal"
} | ConvertTo-Json

Write-Host $job_request
```

**Expected output:**
```json
{
  "test_name": "GET_RO_Number_Load",
  "script_path_on_vm": "L:\\Latest_Script_Sqlserver\\Xinsepect_RDS_SQL&BabelfishTestplan_Latest_07_21.jmx",
  "shared_root": "L:\\Testlogfiles\\MCP_Testlogfiles_entry",
  "notification_channel": "terminal"
}
```

---

### Step 4.2: Test Tool 2 - get_execution_status

**Command:**
```powershell
# Query job status

$status_request = @{
    job_id = "14-30-22_GET_RO_Load_ABC123"
    shared_root = "L:\Testlogfiles\MCP_Testlogfiles_entry"
} | ConvertTo-Json

Write-Host $status_request
```

**Expected output:**
```json
{
  "job_id": "14-30-22_GET_RO_Load_ABC123",
  "shared_root": "L:\\Testlogfiles\\MCP_Testlogfiles_entry"
}
```

---

### Step 4.3: Test Tool 3 - generate_daily_report

**Command:**
```powershell
# Generate report for a specific date

$report_request = @{
    shared_root = "L:\Testlogfiles\MCP_Testlogfiles_entry"
    date = "2026-04-29"
    test_name = $null
    notification_channel = "terminal"
} | ConvertTo-Json

Write-Host $report_request
```

**Expected output:**
```json
{
  "shared_root": "L:\\Testlogfiles\\MCP_Testlogfiles_entry",
  "date": "2026-04-29",
  "test_name": null,
  "notification_channel": "terminal"
}
```

---

## Phase 5: Configuration & Environment

### Step 5.1: Set Environment Variables

**Create `.env` file in `mcp-server/` root:**

```bash
# File: mcp-server/.env

# Local MCP-accessible UNC path to shared test results folder
# Note: Tool input can still use VM path L:\Testlogfiles\MCP_Testlogfiles_entry
PERF_SHARED_ROOT=\\your-vm-host\MCP_Testlogfiles_entry

# Optional: Teams webhook (leave empty to skip Teams notifications)
TEAMS_WEBHOOK_URL=https://outlook.webhook.office.com/webhookb2/YOUR-WEBHOOK-URL

# Optional: Slack webhook (leave empty to skip Slack notifications)
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR-WEBHOOK-URL

# Notification channel: "terminal", "teams", "slack", or "both"
NOTIFICATION_CHANNEL=terminal
```

**Then reload the server:**
```powershell
# Kill the running server (Ctrl+C in the terminal where it's running)

# Restart it
.\.venv\Scripts\python.exe -m perf_mcp.server
```

---

### Step 5.2: Verify Environment Variables Are Loaded

```powershell
# Check if .env file exists
Test-Path mcp-server\.env

# View environment (do NOT commit .env!)
cat mcp-server\.env
```

---

## Phase 6: Daily Operations

### Step 6.1: Start Server (Daily)

```powershell
cd "C:\Users\erraguntlaaditya\OneDrive - Nagarro\Documents\Practice\MCPServer\Performance_TestExecution&Reporting"

.\.venv\Scripts\Activate.ps1

.\.venv\Scripts\python.exe -m perf_mcp.server
```

**Keep this terminal open.** The server will run indefinitely.

---

### Step 6.2: Queue a Test Job

**In a separate terminal:**

```powershell
# Navigate to repo root
cd "C:\Users\erraguntlaaditya\OneDrive - Nagarro\Documents\Practice\MCPServer\Performance_TestExecution&Reporting"

# Create job JSON
$job = @{
    test_name = "GET_RO_Number_Load"
    script_path_on_vm = "L:\Latest_Script_Sqlserver\Xinsepect_RDS_SQL&BabelfishTestplan_Latest_07_21.jmx"
    shared_root = "L:\Testlogfiles\MCP_Testlogfiles_entry"
    notification_channel = "terminal"
}

# Send to MCP server (via mcp client - implementation depends on your MCP client)
Write-Host ($job | ConvertTo-Json)
```

**In MCP server terminal, you should see:**
```
[14:30:22] 🚀 TEST EXECUTION STARTED — Job: GET_RO_Number_Load | Round: 1 | Folder: 2026-04-29_Round1_14-30-22
[14:31:22] ⏳ HEARTBEAT — Elapsed: 1 min | Status: RUNNING | VM Runner active
[15:00:45] ✅ TEST COMPLETED — Requests: 180,240 | Errors: 0.82% | Avg: 420ms
[15:00:46] 📊 REPORTING STARTED — Scanning 2026-04-29 | Rounds found: 2
```

---

### Step 6.3: Monitor Active Jobs

```powershell
# Check job status
$status = @{
    job_id = "14-30-22_GET_RO_Number_Load_ABC123"
    shared_root = "L:\Testlogfiles\MCP_Testlogfiles_entry"
}

Write-Host ($status | ConvertTo-Json)
```

---

### Step 6.4: Generate Daily Report

```powershell
# Generate report for today
$report = @{
    shared_root = "L:\Testlogfiles\MCP_Testlogfiles_entry"
    date = (Get-Date -Format "yyyy-MM-dd")
    test_name = $null
    notification_channel = "terminal"
}

Write-Host ($report | ConvertTo-Json)
```

**Expected output:**
```
[15:01:02] 📊 REPORTING STARTED — Scanning 2026-04-29 | Rounds found: 2
[15:01:03] 📋 PARSED Round 1 — 180,240 requests | Avg: 420ms | P95: 980ms
[15:01:04] 📋 PARSED Round 2 — 180,240 requests | Avg: 435ms | P95: 1050ms
[15:01:05] ✅ REPORT GENERATED — Path: L:\Testlogfiles\MCP_Testlogfiles_entry\results\DAILY_REPORT_2026-04-29.html
[15:01:06] ✅ NOTIFICATION SENT — Channel: teams | Status: delivered
```

---

## Phase 7: Troubleshooting

### Issue: Virtual Environment Not Found

```powershell
# Solution: Recreate it
.\setup.ps1
```

### Issue: Dependencies Missing

```powershell
# Solution: Reinstall dependencies
cd mcp-server

uv sync --upgrade
```

### Issue: MCP Server Won't Start

```powershell
# Check Python is working
python --version

# Check if uv can find the project
uv run --help

# Run verbose startup
.\.venv\Scripts\python.exe -m perf_mcp.server
```

### Issue: Tests Fail

```powershell
# Run tests with verbose output (from project root)
.\.venv\Scripts\python.exe -m pytest mcp-server/tests/ -vv

# Run single failing test
.\.venv\Scripts\python.exe -m pytest mcp-server/tests/test_jtl_parser.py::TestParseJtlHappyPath::test_single_label -vv
```

### Issue: UNC Path Not Accessible

```powershell
# Verify the UNC path is reachable
Test-Path "\\your-vm-host\MCP_Testlogfiles_entry"

# Mount the UNC path
New-PSDrive -Name "PerfTest" -PSProvider FileSystem -Root "\\your-vm-host\MCP_Testlogfiles_entry"

# Verify mount
Get-PSDrive PerfTest
```

---

## Phase 8: Maintenance

### Step 8.1: Pull Latest Changes from GitHub

```powershell
cd "C:\Users\erraguntlaaditya\OneDrive - Nagarro\Documents\Practice\MCPServer\Performance_TestExecution&Reporting"

git pull origin main
```

### Step 8.2: Commit Local Changes

```powershell
# Check what changed
git status

# Stage changes
git add .

# Commit with meaningful message
git commit -m "chore: update configuration for production VM"

# Push to GitHub
git push origin main
```

### Step 8.3: Check Repository Status

```powershell
# Verify local matches GitHub
git status

# View commit history
git log --oneline -5

# Check remote configuration
git remote -v
```

---

## Phase 9: Security Checklist

✅ **Before Production Deployment:**

- [ ] `.env` file is in `.gitignore` (secrets NOT in Git)
- [ ] No hardcoded webhook URLs in code
- [ ] All credentials use environment variables
- [ ] UNC path uses service account (not personal credentials)
- [ ] GitHub credentials in Windows Credential Manager (not plain text)
- [ ] MCP server runs with minimal privileges (not as admin)
- [ ] Firewall allows VM ↔ Local communication on UNC share port (445)

**Verify security:**

```powershell
# Check for secrets in code
cd mcp-server

$patterns = @('password\s*=','api[_-]?key\s*=','token\s*=','secret\s*=')

foreach ($p in $patterns) {
    $hits = Select-String -Path (Get-ChildItem -Recurse -File src, tests | % FullName) `
        -Pattern $p -ErrorAction SilentlyContinue
    if ($hits) { $hits | % { "{0}:{1}: {2}" -f $_.Path, $_.LineNumber, $_.Line.Trim() } }
}

Write-Host "✅ Security audit complete"
```

---

## Quick Command Reference

```powershell
# === SETUP ===
.\setup.ps1                                 # First-time setup

# === SERVER ===
.\.venv\Scripts\Activate.ps1                # Activate virtual environment
.\.venv\Scripts\python.exe -m perf_mcp.server  # Start MCP server

# === TESTING ===
.\.venv\Scripts\python.exe -m pytest mcp-server/tests/ -q                                  # Run all tests
.\.venv\Scripts\python.exe -m pytest mcp-server/tests/ --cov=mcp-server/src/perf_mcp -q   # Run with coverage
.\.venv\Scripts\python.exe -m pytest mcp-server/tests/test_jtl_parser.py -v               # Test specific module

# === GIT ===
git status                                   # Check status
git pull origin main                        # Get latest changes
git commit -m "message"                     # Commit changes
git push origin main                        # Push to GitHub

# === TROUBLESHOOTING ===
python --version                            # Check Python
uv --version                                # Check uv
Test-Path mcp-server\.venv                  # Verify virtualenv
```

---

## Support & Contact

- **GitHub Repo:** https://github.com/SriAdityaE/Performance_TestExecution-Reporting.git
- **Issues:** Create GitHub issues for bugs
- **Documentation:** See ARCHITECTURE.md for design details

---

**Version History:**
- v1.0.0 (April 29, 2026) — Initial runbook created with all phases

