# Project Kickoff Checklist — Performance Test Execution & Reporting

**Purpose:** Day 0 setup checklist. Complete ALL items before writing any feature code.
**Rule:** Every checkbox must be ticked before development begins.

---

## Phase 1: Foundation Setup

### Task 1.1: Governance Files (Already Complete for This Project)

- [x] `.github/copilot-instructions.md` — Project-specific rules, tool contracts, report format
- [x] `.github/AI_DEVELOPMENT_STANDARDS.md` — 7 non-negotiable rules
- [x] `.github/AI_COLLABORATION_GUIDE.md` — How to work with AI agents
- [x] `.github/BEFORE_EACH_FEATURE.md` — Pre-implementation checklist
- [x] `.github/BEFORE_EACH_COMMIT.md` — Pre-commit audit checklist
- [x] `.github/PROJECT_KICKOFF_CHECKLIST.md` — This file

**Verification:**
```powershell
Get-ChildItem ".github\" | Select-Object Name
# Should show all 6 governance files
```

---

### Task 1.2: Architecture & TRD Documents

- [ ] `ARCHITECTURE.md` exists with component diagram and responsibilities
- [ ] `TRD.md` exists with full functional and non-functional requirements
- [ ] Architecture reviewed and approved by project owner
- [ ] Component boundaries clearly defined:
  - MCP Server owns: JTL parsing, report generation, job queue writing, notification dispatch
  - VM Runner owns: JMeter execution, heartbeat writing, result folder creation
  - VS Code Extension owns: user interface, MCP client invocation

---

### Task 1.3: Project Folder Structure

Create the following structure before any code is written:

```
Performance_TestExecution&Reporting\
├── .github\
│   ├── copilot-instructions.md      ✅
│   ├── AI_DEVELOPMENT_STANDARDS.md ✅
│   ├── AI_COLLABORATION_GUIDE.md   ✅
│   ├── BEFORE_EACH_FEATURE.md      ✅
│   ├── BEFORE_EACH_COMMIT.md       ✅
│   └── PROJECT_KICKOFF_CHECKLIST.md ✅
│
├── mcp-server\
│   ├── src\
│   │   └── perf_mcp\
│   │       ├── __init__.py
│   │       ├── server.py            ← 3 MCP tools here
│   │       ├── jtl_parser.py        ← JTL CSV parsing logic
│   │       ├── report_generator.py  ← HTML report creation
│   │       ├── notifier.py          ← Teams/Slack webhook sender
│   │       └── models.py            ← Pydantic input/output schemas
│   ├── tests\
│   │   ├── test_jtl_parser.py
│   │   ├── test_report_generator.py
│   │   ├── test_notifier.py
│   │   └── test_server.py
│   ├── pyproject.toml
│   └── .env.example                 ← Template, NOT real values
│
├── vm-runner\
│   └── jmeter_runner.ps1            ← PowerShell daemon for VM
│
├── ARCHITECTURE.md
├── TRD.md
├── CHANGELOG.md
├── README.md
├── .gitignore
└── setup.ps1
```

- [ ] Folder structure created
- [ ] All `__init__.py` files created
- [ ] `.gitignore` created and comprehensive

---

### Task 1.4: Environment Setup

**On local machine:**
```powershell
# Navigate to project root
cd "C:\Users\erraguntlaaditya\OneDrive - Nagarro\Documents\Practice\MCPServer\Performance_TestExecution&Reporting"

# Create Python virtual environment in mcp-server
cd mcp-server
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies (after pyproject.toml created)
pip install -e ".[dev]"
```

**On VM:**
- [ ] JMeter installed at known path (e.g., `C:\apache-jmeter\bin\jmeter.bat`)
- [ ] PowerShell 5.1+ available
- [ ] UNC shared folder accessible (test: `Test-Path "\\vm-hostname\PerfTest"`)
- [ ] JMeter test scripts at known path

---

### Task 1.5: Environment Variables Configuration

**Create `.env.example` (safe to commit — no real values):**
```env
# Required
PERF_SHARED_ROOT=\\vm-hostname\PerfTest

# Optional — for Teams notifications
TEAMS_WEBHOOK_URL=https://your-org.webhook.office.com/...

# Optional — for Slack notifications
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# Channel: terminal | teams | slack | both
NOTIFICATION_CHANNEL=terminal

# VM runner settings
JMETER_HOME=C:\apache-jmeter
JMETER_RESULTS_DIR=results
JOB_QUEUE_DIR=__QUEUE__
JOB_RUNNING_DIR=__RUNNING__
RUNNER_POLL_INTERVAL_SECONDS=10
RUNNER_IDLE_TIMEOUT_MINUTES=60
```

**Create `.env` from `.env.example` and fill in real values (never commit):**
```powershell
Copy-Item .env.example .env
notepad .env
```

- [ ] `.env.example` created with all required variables
- [ ] `.env` created locally with real values
- [ ] `.env` verified in `.gitignore`

---

### Task 1.6: .gitignore Creation

```gitignore
# Environment
.env
.env.local

# Python
__pycache__/
*.pyc
*.pyo
.venv/
*.egg-info/
dist/
build/
.pytest_cache/
.coverage
htmlcov/

# Test artifacts (real JTL files — never commit)
*.jtl
results/
temp_results/

# Logs
*.log
*.tmp

# OS
Thumbs.db
.DS_Store
desktop.ini

# IDE
.vscode/settings.json
.idea/

# Node (if VS Code extension added later)
node_modules/
*.tsbuildinfo
*.vsix
```

- [ ] `.gitignore` created before first `git add`

---

### Task 1.7: UNC Shared Folder Setup (VM + Local)

**On VM:**
```powershell
# Create the shared folder structure
$root = "C:\PerfTestShared"
New-Item -ItemType Directory -Path "$root\__QUEUE__" -Force
New-Item -ItemType Directory -Path "$root\__RUNNING__" -Force
New-Item -ItemType Directory -Path "$root\__COMPLETED__" -Force
New-Item -ItemType Directory -Path "$root\results" -Force

# Share the folder (run as Administrator)
New-SmbShare -Name "PerfTest" -Path $root -FullAccess "Everyone"
```

**On local machine:**
```powershell
# Test UNC access
Test-Path "\\vm-hostname\PerfTest"
# Expected: True

# Or map as drive letter (optional)
net use Z: \\vm-hostname\PerfTest
```

- [ ] UNC path accessible from local machine
- [ ] All queue subdirectories created
- [ ] `PERF_SHARED_ROOT` set in `.env`

---

## Phase 2: Readiness Validation

### Checklist: "Are We Ready to Start Coding?"

- [ ] All governance files exist and reviewed
- [ ] Architecture documented with 3 components defined
- [ ] TRD completed with all functional requirements
- [ ] UNC shared folder accessible
- [ ] JMeter installed on VM and test script paths confirmed
- [ ] Python virtual environment works in mcp-server
- [ ] `.env` file created with all required variables
- [ ] `.gitignore` comprehensive and verified
- [ ] Project owner has reviewed and approved architecture

**If ANY checkbox is unchecked → NOT READY.**

---

## Phase 3: AI Training Session & Guardrails

**CRITICAL:** This phase permanently conditions AI to avoid past project mistakes (virtualenv recreation during coding). All answers must be EXACT. No deviation allowed.

---

### 3.1: AI Memorization & Constraint Validation

Before assigning ANY coding task, run this exact script:

```powershell
Write-Host "=== PHASE 3: AI TRAINING VALIDATION ===" -ForegroundColor Green
Write-Host ""
Write-Host "Step 1: Request AI read .github/copilot-instructions.md"
Write-Host "Step 2: Ask the 5 questions below. Answers must be EXACT."
Write-Host ""
```

**Question 1:** "How many MCP tools will this project have?"
- **Expected Answer:** "Exactly 3. No more, no less. Tools are: start_test_execution, get_execution_status, generate_daily_report."
- **Acceptance:** ✅ Only if mentions "exactly 3" AND names all 3 tools

**Question 2:** "Which component executes JMeter tests?"
- **Expected Answer:** "VM PowerShell runner only. MCP server never executes JMeter. MCP only writes job JSON to queue, then reads results."
- **Acceptance:** ✅ Only if explicitly states "MCP never executes"

**Question 3:** "What are the 4 mandatory report sections?"
- **Expected Answer:** "Per-run JMeter results table (with TOTAL row), consolidated comparison table (all rounds side-by-side), key observations (minimum 4 bullets with architect-level analysis), and recommendation paragraph."
- **Acceptance:** ✅ Must list all 4 sections with no omissions

**Question 4:** "Where are ALL secrets and credentials stored?"
- **Expected Answer:** "Environment variables ONLY. Never in code, never in config files, never hardcoded. Use .env file (never committed) and .env.example as template."
- **Acceptance:** ✅ Must explicitly say "environment variables ONLY"

**Question 5:** "What is the communication method between MCP and VM?"
- **Expected Answer:** "Windows UNC file share only. Never SSH, never credentials stored in MCP, never cloud storage. Job queue-based polling via shared folder."
- **Acceptance:** ✅ Must explicitly reject SSH and cloud storage

**If ANY answer is incomplete or wrong:**
```
→ STOP all coding tasks
→ Send AI this message:
   "Your answer to Question X is incomplete. Please re-read 
    .github/copilot-instructions.md, specifically the section on [TOPIC].
    Then re-answer Question X with full detail."
→ Re-validate with the corrected answer
→ Only proceed to next task after ALL 5 answers are 100% correct
```

- [ ] Question 1 answer validated ✅
- [ ] Question 2 answer validated ✅
- [ ] Question 3 answer validated ✅
- [ ] Question 4 answer validated ✅
- [ ] Question 5 answer validated ✅

---

### 3.2: Environment Management Guardrails (CRITICAL)

**PAST PROJECT PROBLEM:** AI repeatedly asked to create virtualenv during feature coding → massive waste of time.

**SOLUTION:** Virtualenv created ONCE in Phase 1.4, then LOCKED and reused for ALL subsequent tasks.

**Virtualenv Lifecycle:**
- **Phase 1.4:** Engineer runs `.\.venv\Scripts\Activate.ps1` ONCE → creates virtualenv
- **All Subsequent Tasks:** AI must use EXISTING virtualenv, never create a new one
- **If AI Requests New Virtualenv During Coding:** REJECT immediately with reference to this checklist

**Rejection Protocol (Copy-Paste Ready):**
```
❌ REJECTED — Virtualenv Recreation Request

This project has ONE virtualenv created during Phase 1.4.
Do NOT create a new virtual environment.

Reference: .github/PROJECT_KICKOFF_CHECKLIST.md — Phase 3.2

Why: Virtualenv recreation is waste of time. One environment
created once, reused for all feature development.

Action: Continue using existing .venv directory.
Verify: Is .venv folder present? → Yes → Continue.
        Is .venv folder missing? → Stop. Re-run Phase 1.4.
```

**To verify virtualenv is present and activate:**
```powershell
cd mcp-server
$env:VIRTUAL_ENV  # Check if already activated
if ($VIRTUAL_ENV) { Write-Host "✅ Virtualenv active: $VIRTUAL_ENV" }
else {
    Write-Host "Activating virtualenv..."
    .\.venv\Scripts\Activate.ps1
}
```

- [ ] Virtualenv created ONCE in Phase 1.4 ✅
- [ ] AI trained: "Never create new virtualenv during feature coding"
- [ ] Rejection protocol saved and ready to paste

---

### 3.3: Security Standards Checklist

**These rules are MANDATORY for every code file.** AI must verify BEFORE committing.

| Standard | Rule | Verification | Pass |
|----------|------|--------------|------|
| **Secrets** | No credentials in code, config, or comments | `grep -r "password\|token\|api_key" src/` → 0 matches | [ ] |
| **Environment Variables** | All secrets loaded from `.env` via `os.getenv()` | Check every MCP tool uses `os.getenv("PERF_SHARED_ROOT")` | [ ] |
| **Logging Safety** | Never log secrets, webhook URLs, or personal data | Audit all `print()` and `logger.*()` statements | [ ] |
| **SSH Protection** | Never use SSH or paramiko — UNC file share only | No SSH imports, no `"ssh"` strings in code | [ ] |
| **Cloud Storage** | No AWS S3, Azure Blob, GCS — only Windows UNC | No boto3, azure-blob-storage, or google-cloud imports | [ ] |
| **.env File** | `.env` in `.gitignore`, never committed | `git status --ignored \| grep .env` → shows ignored | [ ] |
| **Webhook URLs** | Teams/Slack URLs in `.env`, never hardcoded | All webhooks fetched via `os.getenv("TEAMS_WEBHOOK_URL")` | [ ] |

**Before ANY commit, run:**
```powershell
# Check for hardcoded secrets
grep -r "password\|api_key\|token\|webhook" src/ --include="*.py"
# Expected output: NOTHING

# Check .env is ignored
git check-ignore .env
# Expected output: .env (matched by pattern .env)

# Verify no SSH imports
grep -r "import paramiko\|import ssh" src/
# Expected output: NOTHING
```

If ANY check fails → DO NOT COMMIT. Fix first.

- [ ] All security standards validated before first commit

---

### 3.4: Performance Standards Checklist

**These timeouts and limits are MANDATORY.** Never deviate. Defined in TRD.md NFR-003 and NFR-004.

| Operation | Timeout / Limit | Standard | Verification |
|-----------|-----------------|----------|--------------|
| **JTL CSV Parsing** | 30 seconds max | Parse 100,000+ rows without exceeding limit | Function includes timeout wrapper |
| **HTML Report Generation** | 60 seconds max | Generate 4-section report with comparison in <60s | Timer logs time spent |
| **Teams/Slack Webhook** | 12 seconds max | POST notification with 3-retry logic, fail-open | `requests.post(..., timeout=12)` |
| **UNC File Operations** | 10 seconds max | Read/write to shared folder, retry on lock conflict | All file I/O has timeout |
| **JTL Size Limit** | 150,000 characters max | Truncate large JTL before parsing if exceeds limit | Validation in `parse_jtl()` |
| **Report Cache** | TTL-based LRU | Cache HTML report for same day/test, max 10 entries | Redis-free, in-memory only |
| **Live Log Tail Buffer** | Last 100 lines | Mirror VM runner output to terminal (last 100 lines max) | `tail -n 100` equivalent logic |

**Implementation Checklist:**
- [ ] Every network call has `timeout=12` parameter
- [ ] JTL parser includes 30-second timeout wrapper
- [ ] Report generator includes 60-second timer with logging
- [ ] UNC file I/O wrapped in retry loop with 10s timeout
- [ ] JTL size validated before parsing (150K char limit)
- [ ] Live log tailing limited to last 100 lines
- [ ] No unbounded loops or infinite retries

---

### 3.5: Before ANY Feature Coding — Final Validation

**This checklist runs AFTER Phase 3.1-3.4 are complete.**

```
🚀 READY TO CODE? Verify:

☐ AI passed all 5 training questions (Phase 3.1)
☐ AI confirmed: "Virtualenv created once, never recreate" (Phase 3.2)
☐ AI confirmed: "Never store secrets in code" (Phase 3.3)
☐ AI confirmed: "All operations have timeouts" (Phase 3.4)
☐ All governance files (.github/) reviewed by engineer
☐ TRD requirements understood (FR-001 to FR-009, NFR-001 to NFR-004)
☐ Architecture diagram reviewed (3 components: MCP, VM Runner, UNC Share)
☐ Project owner has signed off: "Ready to code"

If ANY item is unchecked → STOP. Do not assign any coding task.
```

- [ ] All Phase 3 checkboxes complete
- [ ] Project owner review and approval complete
- [ ] Ready to assign coding tasks

---

### 3.6: If AI Violates Constraints During Development

**This section is for the engineer (you). If AI violates any rule mid-project:**

**Violation: AI asks to create virtualenv**
```
IMMEDIATE RESPONSE:
"❌ REJECTED — Virtualenv Recreation Request
Reference: .github/PROJECT_KICKOFF_CHECKLIST.md — Phase 3.2
Continue using existing .venv. No new environments."
```

**Violation: AI suggests storing secrets in code**
```
IMMEDIATE RESPONSE:
"❌ REJECTED — Hardcoded Secrets
Reference: .github/copilot-instructions.md — Security Policy
Use os.getenv() and .env files ONLY."
```

**Violation: AI suggests using SSH or cloud storage**
```
IMMEDIATE RESPONSE:
"❌ REJECTED — Forbidden Architecture
Reference: .github/copilot-instructions.md — Architecture Constraints
UNC file share only. No SSH, no cloud storage, no paramiko."
```

**Violation: AI adds 4th MCP tool or deviates from 3-tool limit**
```
IMMEDIATE RESPONSE:
"❌ REJECTED — Tool Count Violation
Reference: .github/AI_DEVELOPMENT_STANDARDS.md — Standard 1
Exactly 3 tools only. No exceptions. Remove the 4th tool immediately."
```

**General Rule:** If AI violates a rule, reply with the reference link, paste this checklist section, and ask AI to re-read the relevant governance file before continuing.

- [ ] Violation protocol understood and ready to enforce

---

## Phase 4: Week 1 Delivery Plan

| Day | Deliverable | Owner |
|-----|-------------|-------|
| Day 1 | `.github/` governance files, TRD, ARCHITECTURE.md | AI + Review |
| Day 2 | Pydantic models, `jtl_parser.py`, unit tests | AI + Review |
| Day 3 | `start_test_execution` + `get_execution_status` tools + terminal notifications | AI + Review |
| Day 4 | `generate_daily_report` tool + HTML report generator + comparison logic | AI + Review |
| Day 5 | VM PowerShell runner, Teams/Slack notifier, integration test | AI + Review |

---

**Version:** 1.0
**Created:** April 29, 2026
**Project:** Performance Test Execution & Reporting
