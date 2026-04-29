# Architecture Document
# Performance Test Execution & Reporting

| Field | Value |
|-------|-------|
| **Version** | 1.0 |
| **Date** | April 29, 2026 |
| **Status** | Approved |

---

## 1. Architecture Overview

This system uses a 3-component architecture:
1. **Local MCP Server** — orchestration, reporting, notifications
2. **Windows UNC File Share** — the ONLY communication channel
3. **Remote VM PowerShell Runner** — JMeter execution only

The design principle is **credential-free remote execution**:
- MCP server never connects to VM
- VM runner never connects to MCP server
- They communicate exclusively through files on shared storage

---

## 2. Component Diagram

```
╔══════════════════════════════════════════════════════════════════╗
║  LOCAL MACHINE (Engineer's Windows PC)                           ║
║                                                                  ║
║  ┌────────────────────┐    stdio     ┌──────────────────────┐   ║
║  │  VS Code / CLI     │◄────────────►│  FastMCP Server      │   ║
║  │                    │             │  (Python)             │   ║
║  │  Invokes:          │             │                       │   ║
║  │  start_test_exec.  │             │  ┌─────────────────┐  │   ║
║  │  get_exec_status   │             │  │ start_test_exec │  │   ║
║  │  gen_daily_report  │             │  │ ─ Job creator   │  │   ║
║  │                    │             │  │ ─ Status poller │  │   ║
║  │  Terminal shows:   │             │  │ ─ Heartbeat     │  │   ║
║  │  All events with   │             │  └─────────────────┘  │   ║
║  │  timestamps        │             │                       │   ║
║  │                    │             │  ┌─────────────────┐  │   ║
║  └────────────────────┘             │  │ get_exec_status │  │   ║
║                                     │  │ ─ Status reader │  │   ║
║  ┌────────────────────┐             │  │ ─ KPI extractor │  │   ║
║  │  Teams / Slack     │◄────────────│  └─────────────────┘  │   ║
║  │  (optional, env)   │  webhooks   │                       │   ║
║  └────────────────────┘             │  ┌─────────────────┐  │   ║
║                                     │  │ gen_daily_report│  │   ║
║                                     │  │ ─ JTL parser    │  │   ║
║                                     │  │ ─ Comparator    │  │   ║
║                                     │  │ ─ HTML generator│  │   ║
║                                     │  │ ─ Notifier      │  │   ║
║                                     │  └─────────────────┘  │   ║
║                                     └──────────┬────────────┘   ║
║                                                │                  ║
╚════════════════════════════════════════════════│══════════════════╝
                                                 │
                          ╔══════════════════════▼══════════════════╗
                          ║  WINDOWS UNC FILE SHARE                 ║
                          ║  \\vm-hostname\PerfTest\                ║
                          ║  (configured via PERF_SHARED_ROOT env)  ║
                          ║                                         ║
                          ║  __QUEUE__\          ← MCP writes       ║
                          ║  __RUNNING__\        ← Runner moves     ║
                          ║  __COMPLETED__\      ← Runner archives  ║
                          ║  results\                               ║
                          ║    YYYY-MM-DD_RoundN_HH-MM-SS\         ║
                          ║      *.jtl         (JMeter output)     ║
                          ║      metadata.json (job + status)      ║
                          ║      summary.json  (parsed KPIs)       ║
                          ║      heartbeat.json (runner pulse)     ║
                          ║      runner_live.log (live VM stream)  ║
                          ║    DAILY_REPORT_YYYY-MM-DD.html        ║
                          ╚══════════════════════╤══════════════════╝
                                                 │
╔════════════════════════════════════════════════│══════════════════╗
║  REMOTE VM (Windows Server — RDP access only)  │                  ║
║                                                │                  ║
║  ┌─────────────────────────────────────────────▼──────────────┐  ║
║  │  PowerShell Runner Daemon                                   │  ║
║  │  (started manually in Command Prompt by engineer)          │  ║
║  │                                                             │  ║
║  │  Loop every 10 seconds:                                     │  ║
║  │  1. Scan __QUEUE__\ for *.json job files                    │  ║
║  │  2. Move job file → __RUNNING__\                            │  ║
║  │  3. Execute: jmeter.bat -n -t [script.jmx] -l results.jtl │  ║
║  │  4. JMeter runs in SAME Command Prompt window (visible)     │  ║
║  │  5. Write heartbeat.json every 60s during execution        │  ║
║  │  6. Write metadata.json (status: running → completed)      │  ║
║  │  7. Move job file → __COMPLETED__\                          │  ║
║  │  8. Wait 60 min for next job, then shutdown                 │  ║
║  └─────────────────────────────────────────────────────────────┘  ║
║                                                                    ║
╚════════════════════════════════════════════════════════════════════╝
```

---

## 3. Component Responsibilities

### 3.1 FastMCP Server (Local — `mcp-server/src/perf_mcp/server.py`)

**OWNS:**
- All 3 MCP tool definitions and their logic
- Job file creation (writing to `__QUEUE__`)
- Status polling (reading from `results` folder)
- Live VM stream tailing (reading from `runner_live.log`)
- JTL CSV parsing and KPI computation
- Round-to-round comparison and delta calculation
- HTML report generation (all 4 sections)
- Expert observation generation
- Terminal notification dispatch (all events)
- Teams/Slack webhook delivery

**DOES NOT OWN:**
- JMeter execution (VM runner owns this)
- Heartbeat file writing (VM runner owns this)
- summary.json creation (VM runner owns this)
- Any remote connection to VM
- Any cloud storage operations

---

### 3.2 PowerShell VM Runner (Remote — `vm-runner/jmeter_runner.ps1`)

**OWNS:**
- JMeter test execution via `jmeter.bat -n -t ...`
- Heartbeat file writing (every 60 seconds)
- metadata.json creation and status updates
- summary.json creation after test completion (basic KPIs)
- Result folder creation (`YYYY-MM-DD_RoundN_HH-MM-SS`)
- results.jtl placement in result folder
- Job file lifecycle: queued → running → completed/failed

**DOES NOT OWN:**
- Report generation (MCP server owns this)
- HTML creation (MCP server owns this)
- Notification sending (MCP server owns this)
- Comparison analysis (MCP server owns this)
- Any network calls (webhook, API, etc.)

---

### 3.3 UNC File Share (Communication Layer)

**OWNS:**
- Persistent storage of job queue files
- Persistent storage of result folders
- Persistent storage of HTML reports

**Structure enforced:**
```
SHARED_ROOT\
├── __QUEUE__\                              ← Job files waiting for runner
│   └── 14-30-22_GET_RO_Number_abc123.json
│
├── __RUNNING__\                            ← Job currently in progress
│   └── 14-30-22_GET_RO_Number_abc123.json
│
├── __COMPLETED__\                          ← Archived job files
│   └── 14-30-22_GET_RO_Number_abc123.json
│
└── results\
    ├── 2026-04-29_Round1_14-30-22\
   │   ├── GET_RO_Number_Round1.jtl        ← JMeter output (CSV, name can vary)
    │   ├── metadata.json                   ← Execution metadata
    │   ├── summary.json                    ← Basic KPIs from runner
    │   └── heartbeat.json                  ← Runner pulse file
   │   └── runner_live.log                 ← VM command prompt stream
    │
    ├── 2026-04-29_Round2_15-45-10\
   │   ├── GET_RO_Number_Round2.jtl
    │   ├── metadata.json
    │   ├── summary.json
   │   ├── heartbeat.json
   │   └── runner_live.log
    │
    └── DAILY_REPORT_2026-04-29.html        ← Final stakeholder report
```

**Compatibility rule:** For historical result folders that do not follow naming convention, MCP must still discover same-day runs using artifact detection (`*.jtl` + `metadata.json`) and metadata timestamps.

---

## 4. Data Flow

### 4.1 Test Execution Flow

```
1. Engineer runs:
   MCP > start_test_execution(test_name, script_path, shared_root, channel)

2. MCP Server:
   a. Counts YYYY-MM-DD_Round* folders → N = next round number
   b. Generates job_id = HH-MM-SS_testName_XXXXXX
   c. Creates result folder: results\YYYY-MM-DD_RoundN_HH-MM-SS\
   d. Writes job file: __QUEUE__\job_id.json
   e. Prints: [HH:MM:SS] ✅ JOB QUEUED
   f. Enters monitoring loop (polls every 60 seconds)

3. VM Runner (within 10 seconds):
   a. Scans __QUEUE__\ → finds job_id.json
   b. Moves to __RUNNING__\
   c. Writes metadata.json (status: running, started_at: ...)
   d. Executes: jmeter.bat -n -t [script.jmx] -l results\day_folder\results.jtl
   e. JMeter runs visibly in Command Prompt window
   f. Writes heartbeat.json every 60 seconds
   g. Appends command prompt output to results\day_folder\runner_live.log

4. MCP Monitoring Loop:
   a. Tails runner_live.log continuously → prints [HH:MM:SS] 📋 VM_STREAM — [line]
   b. Every 60s: reads heartbeat.json → prints [HH:MM:SS] ⏳ HEARTBEAT
   c. Checks metadata.json status
   d. If live log unavailable: prints [HH:MM:SS] ⚠️ MONITORING_FALLBACK and continues heartbeat-only mode
   e. If status = completed → proceeds to step 5
   f. If elapsed > 120 min → prints TIMED OUT, exits loop

5. On Test Completion (VM Runner):
   a. Writes final metadata.json (status: completed, completed_at: ...)
   b. Writes summary.json (basic KPIs)
   c. Moves job file to __COMPLETED__\

6. MCP Server (after detecting completion):
   a. Prints: [HH:MM:SS] ✅ TEST COMPLETED — Requests: X | Errors: Y% | Avg: Zms
   b. Automatically calls generate_daily_report for that date
```

---

### 4.2 Report Generation Flow

```
1. Trigger: automatic (post-completion) OR manual call to generate_daily_report

2. MCP Server:
   a. Scans results\ for YYYY-MM-DD_Round* folders
   b. Prints: [HH:MM:SS] 📊 REPORTING STARTED — N rounds found

3. For each round folder:
   a. Discovers and opens run JTL file using *.jtl (CSV)
   b. Parses per-label rows + computes TOTAL row
   c. Computes: avg, median, p90, p95, p99, min, max, error_rate, throughput
   d. Prints: [HH:MM:SS] 📋 PARSED Round N — X requests | Avg: Yms | P95: Zms

4. Comparison:
   a. Round1 vs Round2: delta calculation for all KPIs
   b. Round2 vs Round3: delta calculation (if applicable)
   c. Round1 vs RoundN (first-vs-last): summary (if 3+ rounds)

5. Observation Generation:
   a. Trend analysis: is performance improving or degrading?
   b. Percentile analysis: p95/p99 SLA risk?
   c. Max response time: tail latency spike risk?
   d. Error rate: reliability trend?
   e. Throughput: capacity confirmed or degraded?
   f. Root cause hypothesis if degradation detected

6. HTML Generation:
   a. Section 1: Per-run table for each round (with TOTAL row)
   b. Section 2: Consolidated comparison table (all rounds side-by-side)
   c. Section 3: Key Observations (4+ bullet points)
   d. Section 4: Recommendation paragraph
   e. Save as: results\DAILY_REPORT_YYYY-MM-DD.html

7. Notification:
   a. Teams webhook (if TEAMS_WEBHOOK_URL set)
   b. Slack webhook (if SLACK_WEBHOOK_URL set)
   c. Prints: [HH:MM:SS] ✅ REPORT GENERATED — Path: X
   d. Prints: [HH:MM:SS] ✅ NOTIFICATION SENT — Channel: X
```

---

## 5. File Schemas

### 5.1 Job File Schema (`__QUEUE__\job_id.json`)

```json
{
  "job_id": "14-30-22_GET_RO_Number_abc123",
  "test_name": "GET_RO_Number",
  "script_path_on_vm": "C:\\PerfTests\\Scripts\\GET_RO_Number.jmx",
  "round": 1,
  "day_folder": "2026-04-29_Round1_14-30-22",
  "created_at": "2026-04-29T14:30:22",
  "notification_channel": "teams",
  "status": "queued"
}
```

### 5.2 Metadata File Schema (`results\day_folder\metadata.json`)

```json
{
  "job_id": "14-30-22_GET_RO_Number_abc123",
  "test_name": "GET_RO_Number",
  "script_path_on_vm": "C:\\PerfTests\\Scripts\\GET_RO_Number.jmx",
  "round": 1,
  "day_folder": "2026-04-29_Round1_14-30-22",
  "status": "completed",
  "started_at": "2026-04-29T14:30:35",
  "completed_at": "2026-04-29T15:00:45",
  "duration_minutes": 30.16,
  "exit_code": 0,
  "error_message": null
}
```

### 5.3 Summary File Schema (`results\day_folder\summary.json`)

```json
{
  "job_id": "14-30-22_GET_RO_Number_abc123",
  "total_requests": 144237,
  "failed_requests": 0,
  "error_rate_pct": 0.00,
  "avg_response_ms": 14.0,
  "median_ms": 11.0,
  "p90_ms": 24.0,
  "p95_ms": 29.0,
  "p99_ms": 33.0,
  "min_ms": 4.0,
  "max_ms": 764.0,
  "throughput_req_sec": 39.01,
  "received_kb_sec": 0.63,
  "sent_kb_sec": 0.0
}
```

### 5.4 Heartbeat File Schema (`results\day_folder\heartbeat.json`)

```json
{
  "job_id": "14-30-22_GET_RO_Number_abc123",
  "last_heartbeat": "2026-04-29T14:45:22",
  "elapsed_minutes": 14.78,
  "status": "running"
}
```

---

## 6. Module Structure

```
mcp-server/
└── src/
    └── perf_mcp/
        ├── __init__.py
        ├── server.py              ← FastMCP server + 3 tool definitions
        ├── jtl_parser.py          ← JTL CSV parsing + percentile calculation
        ├── report_generator.py    ← HTML report creation (all 4 sections)
        ├── comparator.py          ← Round-to-round delta analysis
        ├── observer.py            ← Expert observation text generation
        ├── notifier.py            ← Teams/Slack webhook delivery
        └── models.py              ← All Pydantic input/output schemas
```

### Module Responsibilities

| Module | Owns |
|--------|------|
| `server.py` | MCP tool registration, terminal notifications, orchestration |
| `jtl_parser.py` | CSV parsing, per-label aggregation, percentile computation, TOTAL row |
| `report_generator.py` | HTML template, table rendering, 4-section assembly |
| `comparator.py` | Consecutive delta calculation, first-vs-last summary |
| `observer.py` | Trend analysis text, root cause hypothesis, recommendation paragraph |
| `notifier.py` | Teams webhook, Slack webhook, retry logic |
| `models.py` | Pydantic models for all tool inputs/outputs/internal data |

---

## 7. Security Design

### 7.1 Credential Flow

```
.env file (never committed)
    │
    ▼
Environment Variables
    PERF_SHARED_ROOT     → used in server.py for all file paths
    TEAMS_WEBHOOK_URL    → used in notifier.py only
    SLACK_WEBHOOK_URL    → used in notifier.py only
    NOTIFICATION_CHANNEL → used in server.py to decide dispatch
    JMETER_HOME          → used in jmeter_runner.ps1 only
    │
    ▼
Code reads os.environ.get("VAR_NAME")  ← never hardcoded
    │
    ▼
Logs NEVER include webhook URLs or UNC credentials
```

### 7.2 Input Validation Rules

| Input | Validation |
|-------|------------|
| `test_name` | Regex: `^[a-zA-Z0-9_-]{1,100}$` |
| `shared_root` | Must start with `\\` or drive letter, no `..` traversal |
| `date` | Regex: `^\d{4}-\d{2}-\d{2}$`, valid calendar date |
| `script_path_on_vm` | Must end with `.jmx`, no command injection chars |
| `notification_channel` | Enum: terminal, teams, slack, both |

---

## 8. Design Decisions

### Decision 1: UNC File Share vs API vs SSH

**Choice:** UNC file share

**Reasoning:**
- No credentials stored in MCP server
- Engineer retains full control of VM
- Simple to implement and debug
- Works on any corporate Windows network with VPN
- Files persist across MCP restarts (no state loss)

**Trade-offs:**
- Slightly slower than direct API (seconds, not milliseconds)
- Requires both machines on same VPN/network
- UNC share must be set up manually once

---

### Decision 2: 3 MCP Tools (Not More)

**Choice:** Exactly 3 tools: start, status, report

**Reasoning:**
- `start_test_execution` orchestrates the entire execution lifecycle
- `get_execution_status` is a lightweight query tool (anytime call)
- `generate_daily_report` handles all reporting concerns
- Internal parsing, comparison, and observation are implementation details — not separate tools
- Fewer tools = simpler interface = less surface area for misuse

---

### Decision 3: Terminal as Primary Notification Channel

**Choice:** Terminal print (always on) + webhooks (optional, env-toggled)

**Reasoning:**
- Terminal notifications require zero configuration
- Engineer sees progress without opening browser or chat
- Webhooks fail silently (with logged error) — test result is never blocked
- Teams/Slack is secondary — for async stakeholder visibility

---

### Decision 4: Report Format Fixed to 4 Sections

**Choice:** Mandatory 4-section format (per-run table, consolidated comparison, observations, recommendation)

**Reasoning:**
- Matches real-world stakeholder report format (sample confirmed by project owner)
- Business owners and managers can read without technical background
- Consistent format enables stakeholder expectations management
- AI observation generation is repeatable and auditable

---

**Version:** 1.0
**Created:** April 29, 2026
**Project:** Performance Test Execution & Reporting
**Status:** Approved — ready for implementation
