# Copilot Working Instructions — Performance Test Execution & Reporting

**Read this file completely before every session. These rules are NON-NEGOTIABLE.**
**Every AI agent, tool-call, and code change must comply with every rule in this file.**

---

## Project Overview

| Field | Value |
|-------|-------|
| **Project Type** | Python FastMCP Server + VS Code Extension + PowerShell VM Runner |
| **Purpose** | Orchestrate JMeter test execution on a remote Windows VM, collect results, generate stakeholder-grade performance reports with multi-run comparison, and deliver notifications via terminal + Teams/Slack |
| **Architecture** | Local FastMCP ↔ Windows UNC file share ↔ Remote VM PowerShell runner |
| **Tools Count** | EXACTLY 3 MCP tools — no more, no less |
| **Security** | No credentials in code or config. Environment variables ONLY |
| **Notifications** | Terminal (mandatory/primary) + Teams/Slack (optional/secondary, env-toggled) |

---

## Strict Architecture Constraints — NEVER VIOLATE

1. **EXACTLY 3 MCP tools exist. Never add a 4th.**
   - `start_test_execution` — submits job, orchestrates monitoring loop, delivers terminal notifications
   - `get_execution_status` — returns current job state with metrics from shared folder
   - `generate_daily_report` — scans day folder, compares all rounds, generates HTML + sends notification

2. **No AWS S3, Azure Blob, Redis, or any cloud storage. EVER.**
   - All storage is Windows UNC file share (configurable via env var `PERF_SHARED_ROOT`)
   - Example: `\\vm-hostname\PerfTest` mounted as a network path

3. **No SSH, no VM credentials, no remote execution from MCP.**
   - MCP writes job JSON to UNC `__QUEUE__` folder
   - VM PowerShell runner polls that folder and executes JMeter independently
  - MCP only reads files written by VM runner (including live execution log stream)

4. **JMeter parameterization CSV files are NEVER touched by MCP.**
  - MCP only reads: run JTL output (`*.jtl`, CSV format), `summary.json`, `metadata.json`, `heartbeat.json`, `runner_live.log`
   - MCP never modifies JMeter scripts or data files

5. **Terminal notifications are MANDATORY for every lifecycle event.**
   - No event is silent. Every state change must `print()` with timestamp prefix.

---

## The 3 MCP Tool Contracts

### Tool 1: `start_test_execution`

```python
Input:
  test_name: str           # e.g., "GET_RO_Number_Load"
  script_path_on_vm: str   # e.g., "C:\\PerfTests\\Scripts\\GET_RO_Number.jmx"
  shared_root: str         # UNC path, e.g., "\\\\vm-host\\PerfTest"
  notification_channel: str  # "terminal" | "teams" | "slack" | "both"

Behavior:
  1. Generate job_id = HH-MM-SS_testName_random6chars
  2. Determine round number N by counting existing day folders for today
  3. Create day folder: YYYY-MM-DD_RoundN_HH-MM-SS
  4. Create job JSON in shared_root\__QUEUE__\
  5. Print: [HH:MM:SS] ✅ JOB QUEUED — job_id, round, folder
  6. Start monitoring loop (heartbeat every 60 seconds + live VM stream tail):
     - Check status in shared_root\results\day_folder\metadata.json
     - Tail shared_root\results\day_folder\runner_live.log and mirror VM output to local terminal
     - Print VM lines as: [HH:MM:SS] 📋 VM_STREAM — [line]
     - If live log is temporarily unavailable, fallback to heartbeat-only monitoring (no silent failure)
     - Print: [HH:MM:SS] ⏳ TEST RUNNING — elapsed time, % complete if available
  7. On completion:
     - Print: [HH:MM:SS] ✅ TEST COMPLETED — total requests, error rate, avg response
     - Automatically call generate_daily_report internally
  8. On failure:
     - Print: [HH:MM:SS] ❌ TEST FAILED — error details, result folder path

Output:
  {
    "job_id": str,
    "round": int,
    "day_folder": str,
    "status": "queued" | "running" | "completed" | "failed",
    "result_folder": str,
    "live_log_path": str,
    "monitoring_mode": "live_stream" | "heartbeat_only"
  }
```

### Tool 2: `get_execution_status`

```python
Input:
  job_id: str
  shared_root: str

Behavior:
  1. Scan shared_root for job_id in queued/running/completed/failed folders
  2. Read metadata.json and summary.json if available
  3. Read latest line from runner_live.log if available
  3. Print current status to terminal with timestamp
  4. Return structured status with metrics if available

Output:
  {
    "job_id": str,
    "status": str,
    "test_name": str,
    "started_at": str,
    "completed_at": str | None,
    "metrics": {
      "total_requests": int,
      "avg_response_ms": float,
      "median_ms": float,
      "p90_ms": float,
      "p95_ms": float,
      "p99_ms": float,
      "min_ms": float,
      "max_ms": float,
      "error_rate_pct": float,
      "throughput_req_sec": float,
      "received_kb_sec": float,
      "sent_kb_sec": float
    } | None,
    "result_folder": str,
    "live_log_available": bool,
    "last_vm_log_line": str | None
  }
```

### Tool 3: `generate_daily_report`

```python
Input:
  shared_root: str
  date: str              # "YYYY-MM-DD" — day to report on
  test_name: str | None  # Filter to specific test, or None for all
  notification_channel: str  # "terminal" | "teams" | "slack" | "both"

Behavior:
  1. Scan shared_root\results\ recursively and discover run folders by artifacts (`*.jtl` + `metadata.json`) for the requested date
  2. Print: [HH:MM:SS] 📊 REPORTING STARTED — N rounds found
  3. For each round folder:
  a. Parse run JTL file (CSV format, discovered as `*.jtl`)
     b. Extract all KPIs from JTL
     c. Print: [HH:MM:SS] 📋 PARSED Round N — KPIs summary
  4. Compare consecutive rounds (Round1 vs Round2, Round2 vs Round3, etc.)
  5. Generate first-vs-last summary if 3+ rounds
  6. Generate expert observations (architect-level analysis)
  7. Generate stakeholder-grade HTML report
  8. Print: [HH:MM:SS] ✅ REPORT GENERATED — path, comparison count
  9. Send Teams/Slack notification with HTML path if channel configured

Output:
  {
    "date": str,
    "rounds_found": int,
    "rounds_compared": int,
    "html_report_path": str,
    "notification_status": dict,
    "summary": dict
  }
```

---

## STRICT Report Output Format

**This format is MANDATORY. The HTML and terminal report must match this EXACTLY.**
**This format is based on stakeholder communication requirements. No deviation allowed.**

### Section 1: Per-Run JMeter Results Table

Each round must produce this table:

| Label | # Samples | Average | Median | 90% Line | 95% Line | 99% Line | Min | Max | Error % | Throughput | Received KB/sec | Sent KB/sec |
|-------|-----------|---------|--------|----------|----------|----------|-----|-----|---------|-----------|----------------|-------------|
| [transaction_label] | | | | | | | | | | | | |
| **TOTAL** | | | | | | | | | | | | |

### Section 2: Consolidated Comparison Table (all rounds side by side)

| Metric | Round 1 (label) | Round 2 (label) | Round 3 (label) | ... |
|--------|----------------|----------------|----------------|-----|
| # Samples | | | | |
| Avg Response Time | X ms | X ms | X ms | |
| Median | X ms | X ms | X ms | |
| 90th Percentile | X ms | X ms | X ms | |
| 95th Percentile | X ms | X ms | X ms | |
| 99th Percentile | X ms | X ms | X ms | |
| Min | X ms | – | X ms | |
| Max | X ms | X ms | X ms | |
| Error Rate | 0.00% | 0.00% | 0.00% | |
| Throughput | X req/s | X req/s | X req/s | |

### Section 3: Key Observations (architect-level, minimum 4 bullet points)

Must include:
- Trend across rounds (improving/degrading/stable)
- Percentile analysis (p90/p95/p99 comparison)
- Max response time analysis
- Error rate analysis
- Throughput stability analysis
- Root cause hypothesis if degradation detected

### Section 4: Recommendation

Single clear paragraph. State:
- Which round performed best and why
- Whether to proceed or investigate
- Next steps

---

## Folder Naming Convention — NEVER DEVIATE

```
SHARED_ROOT\
└── results\
    ├── 2026-04-29_Round1_14-30-22\      ← First test on that date
  │   ├── GET_RO_Number_Round1.jtl      ← JMeter CSV JTL output (file name can vary)
    │   ├── metadata.json                 ← job_id, test_name, script_path, timestamps
    │   └── summary.json                  ← parsed KPIs (written by VM runner)
    │
    ├── 2026-04-29_Round2_15-45-10\      ← Second test same date
  │   ├── GET_RO_Number_Round2.jtl
    │   ├── metadata.json
    │   └── summary.json
    │
    ├── 2026-04-29_Round3_16-20-05\      ← Third test same date
  │   ├── GET_RO_Number_Round3.jtl
    │   ├── metadata.json
    │   └── summary.json
    │
    └── DAILY_REPORT_2026-04-29.html     ← Final stakeholder report for that day
```

**Round number N is determined by counting existing `YYYY-MM-DD_Round*` folders for that date at job creation time.**

**Reporting compatibility rule:** For historical folders that do not follow naming convention, MCP must still discover and analyze same-day runs using artifact-based detection (`*.jtl` + `metadata.json`) and metadata timestamps.

---

## JTL Parsing Rules

- JMeter produces `.jtl` in **CSV format** (default JMeter output)
- MCP discovers the JTL file from each round folder using `*.jtl` (name is not fixed to `results.jtl`)
- JTL columns: `timeStamp,elapsed,label,responseCode,responseMessage,threadName,dataType,success,failureMessage,bytes,sentBytes,grpThreads,allThreads,URL,Filename,Latency,Connect,Encoding,SampleCount,ErrorCount,Hostname,IdleTime`
- **Parse per-label AND compute TOTAL row**
- Percentiles (p50/p90/p95/p99) must be computed from raw `elapsed` column — NOT from JMeter summary
- Throughput = total_requests / test_duration_seconds
- Error rate = (error_count / total_requests) * 100
- Average = mean of `elapsed` column per label
- Units: always milliseconds for response times, req/s for throughput, KB/s for bandwidth

---

## Terminal Notification Format (MANDATORY)

Every print must follow this format:
```
[HH:MM:SS] [ICON] [EVENT_TYPE] — [DETAILS]
```

Icons:
- ✅ = success / completed
- ⏳ = in-progress / waiting
- ❌ = error / failed
- 📊 = reporting
- 📋 = data parsed
- 🚀 = started
- ⚠️  = warning

Additional event types:
- `VM_STREAM` = mirrored JMeter live output from VM runner log
- `MONITORING_FALLBACK` = live stream unavailable; heartbeat-only monitoring active

Examples:
```
[14:30:22] 🚀 TEST EXECUTION STARTED — Job: GET_RO_Number_Load | Round: 1 | Folder: 2026-04-29_Round1_14-30-22
[14:31:22] ⏳ HEARTBEAT — Elapsed: 1 min | Status: RUNNING | VM Runner active
[14:32:22] ⏳ HEARTBEAT — Elapsed: 2 min | Status: RUNNING | VM Runner active
[15:00:45] ✅ TEST COMPLETED — Requests: 180,240 | Errors: 0.82% | Avg: 420ms
[15:00:46] 📊 REPORTING STARTED — Scanning 2026-04-29 | Rounds found: 2
[15:01:02] 📋 PARSED Round 1 — 180,240 requests | Avg: 420ms | P95: 980ms
[15:01:03] 📋 PARSED Round 2 — 180,240 requests | Avg: 435ms | P95: 1050ms
[15:01:04] ✅ REPORT GENERATED — Path: \\vm-host\PerfTest\results\DAILY_REPORT_2026-04-29.html
[15:01:05] ✅ NOTIFICATION SENT — Channel: teams | Status: delivered
[15:01:06] 📋 VM_STREAM — summary + 14766 in 00:00:30 = 492.0/s Avg: 2 Min: 1 Max: 165 Err: 0 (0.00%)
[15:01:07] ⚠️ MONITORING_FALLBACK — Live log temporarily unavailable; heartbeat-only mode active
```

---

## VM Runner Behavior (PowerShell daemon)

- Started **manually once** per session by engineer logging into VM via RDP
- Polls `SHARED_ROOT\__QUEUE__\` every 10 seconds for new `.json` job files
- On job pickup: moves job to `__RUNNING__`, opens Command Prompt window to execute JMeter
- Writes heartbeat file every 60 seconds to `result_folder\heartbeat.json`
- Writes live execution output to `result_folder\runner_live.log` (append mode) for local MCP tailing
- On completion: writes `summary.json` and `metadata.json` with final status
- After completion: waits 1 hour for next job before auto-shutdown
- All activity visible in the Command Prompt window on VM for debugging

---

## Security Policy — NON-NEGOTIABLE

1. **No credentials anywhere in code, config, or documentation**
2. **All secrets via environment variables only:**
   ```
   PERF_SHARED_ROOT=\\vm-hostname\PerfTest
   TEAMS_WEBHOOK_URL=https://...
   SLACK_WEBHOOK_URL=https://...
   NOTIFICATION_CHANNEL=terminal
   ```
3. **Never log webhook URLs, UNC credentials, or any token**
4. **Redact all sensitive data before writing to log files**
5. **`.env` file is in `.gitignore` — never commit it**

---

## Python Code Conventions

- **FastMCP** (`from mcp.server.fastmcp import FastMCP`) — no other MCP variants
- **Pydantic models** for ALL tool inputs and outputs — no raw dicts
- **Complete docstrings** on every function: purpose, Args (with types), Returns, Raises, Example
- **Type hints** on every function signature
- **Structured logging**: every exception must log with context (no silent try/except)
- **Resource cleanup**: all file handles in `finally` blocks
- **Timeout**: all network calls (Teams/Slack webhooks) max 12 seconds
- **Cache**: if any caching used, must have TTL + max size + LRU eviction
- **No hardcoded paths** anywhere — use env vars or parameters

---

## Error Handling Patterns

```python
# CORRECT pattern
try:
    result = parse_jtl(jtl_path)
except FileNotFoundError as e:
    logger.error(f"JTL file not found: {jtl_path} — {e}")
    print(f"[{timestamp()}] ❌ JTL PARSE FAILED — File not found: {jtl_path}")
    raise ValueError(f"JTL file not found: {jtl_path}") from e
except Exception as e:
    logger.error(f"Unexpected error parsing JTL: {jtl_path} — {e}", exc_info=True)
    print(f"[{timestamp()}] ❌ JTL PARSE FAILED — Unexpected error: {e}")
    raise

# WRONG pattern — NEVER do this
try:
    result = parse_jtl(jtl_path)
except:
    return None  # Silent failure — FORBIDDEN
```

---

## Testing Requirements

- Minimum **50% unhappy path tests**
- Required test categories:
  - Empty JTL file
  - Malformed JTL (missing columns)
  - Single-round report (no comparison)
  - Two-round comparison (standard case)
  - Three-round comparison (first vs last + consecutive)
  - Missing metadata.json
  - UNC path unavailable
  - Teams/Slack webhook failure (retry logic test)
  - Concurrent job requests
  - Job timeout (runner does not respond within 2 hours)

---

## What NOT to Do — Hard Rules

1. ❌ Never add a 4th MCP tool
2. ❌ Never access VM via SSH or store VM credentials
3. ❌ Never use cloud storage (S3, Azure, GCS)
4. ❌ Never touch JMeter parameterization CSV files
5. ❌ Never deviate from the report format defined above
6. ❌ Never use bare `except:` or `except Exception:` without logging
7. ❌ Never hardcode `\\vm-hostname\PerfTest` — always from env var
8. ❌ Never commit `.env` file
9. ❌ Never send webhook URLs to logs
10. ❌ Never skip terminal notification for any lifecycle event

---

## Change Control

- Do not update code, config, or docs without sharing a summary first
- Before any edit: state what will change, why, and impact on existing behavior
- If change is optional or debatable: ask first
- No refactoring of unrelated code

---

**Version:** 1.0
**Created:** April 29, 2026
**Project:** Performance Test Execution & Reporting
**Owner:** Nagarro Performance Engineering
