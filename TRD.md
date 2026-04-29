# Technical Requirements Document (TRD)
# Performance Test Execution & Reporting

| Field | Value |
|-------|-------|
| **Project** | Performance Test Execution & Reporting |
| **Version** | 1.0 |
| **Date** | April 29, 2026 |
| **Status** | Approved |
| **Owner** | Nagarro Performance Engineering |

---

## 1. Purpose & Scope

### 1.1 Purpose

This document defines the complete technical requirements for a Model Context Protocol (MCP) based system that:
1. Orchestrates JMeter test execution on a remote Windows VM
2. Monitors execution status and delivers real-time terminal progress
3. Collects JMeter JTL results from a shared folder
4. Generates stakeholder-grade performance reports with multi-run comparison
5. Delivers notifications to Teams and Slack channels

### 1.2 In Scope

- FastMCP Python server with exactly 3 MCP tools
- Windows UNC file share as the only communication mechanism
- PowerShell VM runner daemon (started manually)
- JTL CSV parsing and percentile computation
- HTML report generation matching mandated format
- Teams and Slack webhook notification delivery
- Terminal notifications for all lifecycle events

### 1.3 Out of Scope

- SSH remote execution from MCP to VM
- Cloud storage (S3, Azure Blob, GCS)
- JMeter script creation or modification
- JMeter parameterization CSV file management
- Server-side monitoring (CPU, memory, infrastructure metrics)
- VS Code extension UI (Phase 2)

---

## 2. System Overview

### 2.1 High-Level Architecture

```
LOCAL MACHINE                         REMOTE VM (Windows)
─────────────────                     ─────────────────────
FastMCP Server          UNC Share      PowerShell Runner
  start_test_execution ──────────►  Polls __QUEUE__ folder
  get_execution_status ◄──────────  Executes JMeter
  generate_daily_report            Writes results.jtl
                                   Writes metadata.json
Terminal (notifications)           Command Prompt (live view)

Teams / Slack Webhooks
(optional, env-toggled)
```

### 2.2 Communication Protocol

| Source | Destination | Method | Data |
|--------|-------------|--------|------|
| MCP Server | VM Runner | UNC file write | job JSON file in `__QUEUE__` |
| VM Runner | MCP Server | UNC file write | `*.jtl`, metadata.json, summary.json, heartbeat.json, runner_live.log |
| MCP Server | Engineer | Terminal print | Timestamped progress events |
| MCP Server | Teams/Slack | HTTPS POST | Webhook message with report link |

---

## 3. Functional Requirements

### FR-001: Job Creation and Queueing

**Tool:** `start_test_execution`

| ID | Requirement |
|----|-------------|
| FR-001-1 | System SHALL generate a unique job_id formatted as `HH-MM-SS_testName_XXXXXX` (6 random chars) |
| FR-001-2 | System SHALL determine round number N by counting existing `YYYY-MM-DD_Round*` folders in shared results directory |
| FR-001-3 | System SHALL create job JSON file in `SHARED_ROOT\__QUEUE__\job_id.json` |
| FR-001-4 | Job JSON SHALL contain: job_id, test_name, script_path_on_vm, round, day_folder, created_at, notification_channel |
| FR-001-5 | System SHALL print `[HH:MM:SS] ✅ JOB QUEUED` to terminal immediately after creating job file |

**Job JSON Schema:**
```json
{
  "job_id": "14-30-22_GET_RO_Number_abc123",
  "test_name": "GET_RO_Number",
  "script_path_on_vm": "C:\\PerfTests\\GET_RO_Number.jmx",
  "round": 1,
  "day_folder": "2026-04-29_Round1_14-30-22",
  "created_at": "2026-04-29T14:30:22",
  "notification_channel": "teams",
  "status": "queued"
}
```

---

### FR-002: Execution Monitoring

**Tool:** `start_test_execution` (internal monitoring loop)

| ID | Requirement |
|----|-------------|
| FR-002-1 | System SHALL poll `SHARED_ROOT\results\day_folder\metadata.json` every 60 seconds for status updates |
| FR-002-2 | System SHALL print heartbeat to terminal every 60 seconds: `[HH:MM:SS] ⏳ HEARTBEAT — Elapsed: N min` |
| FR-002-3 | System SHALL detect test completion when metadata.json status = "completed" |
| FR-002-4 | System SHALL detect test failure when metadata.json status = "failed" |
| FR-002-5 | System SHALL timeout job after 120 minutes with `[HH:MM:SS] ❌ JOB TIMED OUT` terminal message |
| FR-002-6 | On completion, system SHALL automatically invoke `generate_daily_report` for that date |
| FR-002-7 | System SHALL tail `runner_live.log` and mirror VM JMeter lines to local terminal while test is running |
| FR-002-8 | If `runner_live.log` is unavailable, system SHALL switch to heartbeat-only monitoring and print fallback warning |

---

### FR-003: Status Retrieval

**Tool:** `get_execution_status`

| ID | Requirement |
|----|-------------|
| FR-003-1 | System SHALL scan shared folder for the given job_id in all status folders |
| FR-003-2 | If job is completed, system SHALL return full KPI metrics from summary.json |
| FR-003-3 | System SHALL print current status to terminal with timestamp |
| FR-003-4 | If job not found, system SHALL return structured error: `{"error": "Job not found", "job_id": "..."}` |

**KPI Metrics to Return:**
- total_requests
- successful_requests
- failed_requests
- error_rate_pct
- avg_response_ms *(REQUIRED — average response time)*
- median_ms
- p90_ms
- p95_ms
- p99_ms
- min_ms
- max_ms
- throughput_req_sec
- received_kb_sec
- sent_kb_sec

---

### FR-004: Report Generation

**Tool:** `generate_daily_report`

| ID | Requirement |
|----|-------------|
| FR-004-1 | System SHALL scan `SHARED_ROOT\results\` for all folders matching `YYYY-MM-DD_Round*` for the given date |
| FR-004-2 | System SHALL also support historical folders with non-standard names by discovering run folders through artifacts (`*.jtl` + `metadata.json`) and same-day metadata timestamps |
| FR-004-3 | System SHALL parse discovered JTL file (`*.jtl`, CSV format) for each round |
| FR-004-4 | System SHALL compute per-label AND TOTAL row for all KPIs |
| FR-004-5 | System SHALL compare consecutive rounds: Round1 vs Round2, Round2 vs Round3, etc. |
| FR-004-6 | System SHALL generate first-vs-last summary when 3 or more rounds exist |
| FR-004-7 | System SHALL generate architect-level observations (minimum 4 bullet points) |
| FR-004-8 | System SHALL generate a single actionable recommendation paragraph |
| FR-004-9 | System SHALL save HTML report as `SHARED_ROOT\results\DAILY_REPORT_YYYY-MM-DD.html` |
| FR-004-10 | System SHALL print `[HH:MM:SS] ✅ REPORT GENERATED` to terminal with report path |

---

### FR-005: JTL Parsing

| ID | Requirement |
|----|-------------|
| FR-005-1 | System SHALL parse JTL files in CSV format only |
| FR-005-2 | System SHALL handle JTL files with standard JMeter CSV columns |
| FR-005-3 | System SHALL compute percentiles (p50, p90, p95, p99) from raw `elapsed` column |
| FR-005-4 | System SHALL compute throughput as total_requests / test_duration_seconds |
| FR-005-5 | System SHALL compute error rate as (failed_requests / total_requests) * 100 |
| FR-005-6 | System SHALL group rows by `label` and compute per-label AND TOTAL aggregate |
| FR-005-7 | System SHALL handle empty JTL files gracefully with clear error message |
| FR-005-8 | System SHALL handle JTL files with missing columns with clear error message |

---

### FR-006: HTML Report Format

The HTML report SHALL contain exactly these 4 sections in this order:

**Section 1 — Per-Run JMeter Results Table (one per round)**

| Column | Type | Description |
|--------|------|-------------|
| Label | string | Transaction label from JTL |
| # Samples | integer | Total request count |
| Average | float ms | Mean response time |
| Median | float ms | 50th percentile |
| 90% Line | float ms | 90th percentile |
| 95% Line | float ms | 95th percentile |
| 99% Line | float ms | 99th percentile |
| Min | float ms | Minimum response time |
| Max | float ms | Maximum response time |
| Error % | float % | Error percentage (2 decimal places) |
| Throughput | float req/s | Requests per second |
| Received KB/sec | float | Bandwidth received |
| Sent KB/sec | float | Bandwidth sent |

*Final row must be TOTAL aggregate.*

**Section 2 — Consolidated Comparison Table (all rounds side by side)**

Rows: # Samples, Avg Response Time, Median, 90th Percentile, 95th Percentile, 99th Percentile, Min, Max, Error Rate, Throughput
Columns: one per round with round label

**Section 3 — Key Observations**

Minimum 4 architect-level bullet points covering:
- Performance trend across rounds (improving/degrading/stable with % change)
- Percentile analysis (focus on p95 and p99 — SLA-relevant)
- Max response time analysis (tail latency risk)
- Error rate analysis (reliability trend)
- Throughput stability (capacity confirmation or concern)
- Root cause hypothesis if degradation detected

**Section 4 — Recommendation**

Single paragraph stating:
- Which round performed best and why
- Whether to proceed with the build or investigate further
- Specific next steps if issues found

---

### FR-007: Terminal Notifications

| Event | Format |
|-------|--------|
| Job queued | `[HH:MM:SS] ✅ JOB QUEUED — Job: X \| Round: N \| Folder: Y` |
| Test started | `[HH:MM:SS] 🚀 TEST EXECUTION STARTED — Script: X` |
| Heartbeat | `[HH:MM:SS] ⏳ HEARTBEAT — Elapsed: N min \| Status: RUNNING` |
| Test completed | `[HH:MM:SS] ✅ TEST COMPLETED — Requests: X \| Errors: X% \| Avg: Xms` |
| Test failed | `[HH:MM:SS] ❌ TEST FAILED — Error: X \| Folder: Y` |
| Job timed out | `[HH:MM:SS] ❌ JOB TIMED OUT — Elapsed: 120 min \| Job: X` |
| Reporting started | `[HH:MM:SS] 📊 REPORTING STARTED — Date: X \| Rounds: N` |
| Round parsed | `[HH:MM:SS] 📋 PARSED Round N — Requests: X \| Avg: Xms \| P95: Xms` |
| Report generated | `[HH:MM:SS] ✅ REPORT GENERATED — Path: X` |
| Notification sent | `[HH:MM:SS] ✅ NOTIFICATION SENT — Channel: X \| Status: delivered` |
| Notification failed | `[HH:MM:SS] ❌ NOTIFICATION FAILED — Channel: X \| Error: Y` |

---

### FR-008: Teams/Slack Notifications

| ID | Requirement |
|----|-------------|
| FR-008-1 | System SHALL send notification to Teams if `TEAMS_WEBHOOK_URL` env var is set |
| FR-008-2 | System SHALL send notification to Slack if `SLACK_WEBHOOK_URL` env var is set |
| FR-008-3 | System SHALL skip webhook if `NOTIFICATION_CHANNEL=terminal` |
| FR-008-4 | Notification SHALL include: date, rounds run, best round, worst round, avg response trend, error rate, report path |
| FR-008-5 | System SHALL retry webhook 3 times with exponential backoff (1s, 2s, 4s) on failure |
| FR-008-6 | System SHALL timeout each webhook attempt at 12 seconds |
| FR-008-7 | Webhook failure SHALL NOT block report generation — report is always generated |

---

### FR-009: VM Runner (PowerShell Daemon)

| ID | Requirement |
|----|-------------|
| FR-009-1 | Runner SHALL be started manually once per session in Command Prompt on VM |
| FR-009-2 | Runner SHALL poll `__QUEUE__` folder every 10 seconds for new job files |
| FR-009-3 | Runner SHALL move job file to `__RUNNING__` before starting JMeter |
| FR-009-4 | Runner SHALL execute JMeter in non-GUI mode with output to `results\day_folder\results.jtl` |
| FR-009-5 | Runner SHALL write heartbeat file every 60 seconds: `results\day_folder\heartbeat.json` |
| FR-009-6 | Runner SHALL write `metadata.json` on start and update status on completion/failure |
| FR-009-7 | Runner SHALL keep Command Prompt window open showing JMeter output (for debugging) |
| FR-009-8 | Runner SHALL wait 60 minutes after test completion for next job before shutting down |
| FR-009-9 | Runner SHALL handle one job at a time |
| FR-009-10 | Runner SHALL append command prompt output to `results\day_folder\runner_live.log` for MCP live tailing |

---

## 4. Non-Functional Requirements

### NFR-001: Performance

| ID | Requirement |
|----|-------------|
| NFR-001-1 | JTL parsing SHALL complete within 30 seconds for files up to 500MB |
| NFR-001-2 | HTML report generation SHALL complete within 60 seconds for 3 rounds |
| NFR-001-3 | Webhook delivery SHALL complete within 12 seconds per attempt |
| NFR-001-4 | Heartbeat poll interval SHALL be exactly 60 seconds |
| NFR-001-5 | Job queue pickup by VM runner SHALL occur within 10 seconds of file write |

### NFR-002: Reliability

| ID | Requirement |
|----|-------------|
| NFR-002-1 | Webhook failure SHALL NOT prevent report HTML generation |
| NFR-002-2 | Corrupt JTL rows SHALL be skipped with warning — partial parse is acceptable |
| NFR-002-3 | UNC path unavailability SHALL return structured error (not crash) |
| NFR-002-4 | Job timeout at 120 minutes SHALL mark job as timed_out (not leave it hanging) |
| NFR-002-5 | Live log streaming interruptions SHALL not stop monitoring; system SHALL continue with heartbeat-only fallback |
| NFR-002-6 | Live log mirroring SHALL de-duplicate repeated lines when tail pointer restarts after transient UNC errors |

### NFR-003: Security

| ID | Requirement |
|----|-------------|
| NFR-003-1 | No credentials in any source file |
| NFR-003-2 | All secrets in `.env` file (never committed) |
| NFR-003-3 | Webhook URLs never written to log files |
| NFR-003-4 | UNC path validated for format before use |
| NFR-003-5 | test_name validated: alphanumeric + underscore + hyphen only |
| NFR-003-6 | script_path_on_vm validated: must match allowed prefix from env |

### NFR-004: Maintainability

| ID | Requirement |
|----|-------------|
| NFR-004-1 | All Python functions have complete docstrings |
| NFR-004-2 | All Pydantic models documented with field descriptions |
| NFR-004-3 | Test suite maintained at 50%+ unhappy path ratio |
| NFR-004-4 | No bare `except:` blocks anywhere |

---

## 5. Interface Requirements

### 5.1 MCP Tool Interfaces

All tools use FastMCP (`from mcp.server.fastmcp import FastMCP`).
All inputs and outputs use Pydantic models.
All tools return structured JSON — never plain strings or raw exceptions.

### 5.2 UNC Folder Interface

```
SHARED_ROOT\
├── __QUEUE__\           ← MCP writes new job files here
├── __RUNNING__\         ← VM runner moves active job here
├── __COMPLETED__\       ← VM runner archives completed jobs here
└── results\
    ├── YYYY-MM-DD_RoundN_HH-MM-SS\
    │   ├── results.jtl       ← JMeter output (CSV format)
    │   ├── metadata.json     ← job metadata + status
    │   ├── summary.json      ← parsed KPIs
    │   └── heartbeat.json    ← runner heartbeat (updated every 60s)
    └── DAILY_REPORT_YYYY-MM-DD.html  ← Final stakeholder report
```

### 5.3 Webhook Interface

**Teams Message Shape:**
```json
{
  "text": "**JMeter Test Report — {date}**\n\nRounds: {N}\nBest Round: {X}\nAvg Response: {Y}ms\nError Rate: {Z}%\nReport: {path}"
}
```

**Slack Message Shape:**
```json
{
  "text": "*JMeter Test Report — {date}*\nRounds: {N} | Best: {X} | Avg: {Y}ms | Errors: {Z}%\nReport: {path}"
}
```

---

## 6. Constraints & Assumptions

### Constraints
- Both local machine and VM are Windows
- Both are on the same VPN/network
- UNC file share is the ONLY communication mechanism
- JMeter produces JTL in CSV format
- VM runner is started manually via RDP by engineer
- Maximum 3 MCP tools (architectural constraint)

### Assumptions
- JMeter is installed on VM at path configured in `JMETER_HOME` env var
- UNC share is accessible from local machine before MCP is invoked
- Engineer has already configured JMeter test scripts on VM
- JMeter test script names and paths are known before invoking MCP
- Network bandwidth is sufficient for UNC file transfer of JTL files (<500MB typical)

---

## 7. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| UNC path unavailable | Medium | High | Retry on connection error; actionable error message |
| JTL file corrupt/incomplete | Low | Medium | Partial parse; skip bad rows; warn in report |
| VM runner crashes mid-test | Low | High | 2-hour timeout; folder cleanup on restart |
| Teams webhook rate limited | Low | Low | Retry with backoff; report still generated |
| JTL file >500MB (long test) | Medium | Medium | Streaming parse with pandas chunked reader |
| Round number collision (concurrent jobs) | Low | High | Lock file during round number calculation |

---

**Version:** 1.0
**Created:** April 29, 2026
**Project:** Performance Test Execution & Reporting
**Status:** Approved — ready for implementation
