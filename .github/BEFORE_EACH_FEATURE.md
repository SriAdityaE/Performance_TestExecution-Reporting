# Before Implementing Each Feature — Performance Test Execution & Reporting

**Purpose:** Checklist to run BEFORE writing any code for this project.
**Rule:** AI must complete this checklist and report results before showing any implementation.

---

## PRE-IMPLEMENTATION CHECKLIST

### Step 1: Architecture Verification

- [ ] Identify which of the 3 MCP tools this feature belongs to:
  - `start_test_execution`
  - `get_execution_status`
  - `generate_daily_report`
- [ ] Confirm logic is NOT being placed in VM runner (wrong component)
- [ ] Confirm no 4th MCP tool is being created
- [ ] Confirm no SSH or remote execution logic is being added

**AI Action:**
```
State: "This feature belongs to [TOOL_NAME] because [REASON].
        It will NOT introduce a 4th MCP tool.
        It will NOT use SSH or remote execution."
```

---

### Step 2: Security Pre-Check

- [ ] No hardcoded UNC paths (must use `PERF_SHARED_ROOT` env var)
- [ ] No hardcoded webhook URLs
- [ ] No VM credentials (username/password/key)
- [ ] Input validation planned for all user-supplied paths and strings
- [ ] Path traversal prevention planned for UNC folder access

**AI Action:**
```
State: "Security check passed. All paths from env vars. No credentials.
        Input validation: [DESCRIBE VALIDATION APPROACH]"
```

---

### Step 3: Terminal Notification Planning

List every terminal print statement this feature will emit:

```
Example:
1. [HH:MM:SS] 🚀 TEST EXECUTION STARTED — Job: X | Round: N | Folder: Y
2. [HH:MM:SS] ⏳ HEARTBEAT — Elapsed: N min | Status: RUNNING
3. [HH:MM:SS] ✅ TEST COMPLETED — Requests: X | Errors: X% | Avg: Xms
```

- [ ] Every lifecycle event accounted for
- [ ] All prints include timestamp prefix `[HH:MM:SS]`
- [ ] All prints include relevant metrics/context
- [ ] No silent operations

---

### Step 4: Pydantic Model Design

- [ ] Define input model with all required fields and types
- [ ] Define output model with all response fields and types
- [ ] Add field validators for critical fields (date format, path format, channel enum)
- [ ] Document each field with description

**Example:**
```python
class StartTestExecutionRequest(BaseModel):
    test_name: str = Field(..., description="Test scenario name, alphanumeric + underscore")
    script_path_on_vm: str = Field(..., description="Absolute path to .jmx on VM")
    shared_root: str = Field(..., description="UNC path to shared folder root")
    notification_channel: Literal["terminal", "teams", "slack", "both"] = "terminal"

class StartTestExecutionResponse(BaseModel):
    job_id: str
    round: int
    day_folder: str
    status: Literal["queued", "running", "completed", "failed"]
    result_folder: str
```

---

### Step 5: Failure Scenario Planning

List MINIMUM 5 ways this feature could fail, and planned test case for each:

| # | Failure Scenario | Expected Behavior | Test Function Name |
|---|-----------------|-------------------|-------------------|
| 1 | UNC path unreachable | Raise ValueError with actionable message | `test_unc_path_unreachable_raises_error` |
| 2 | JTL file empty | Raise ValueError("JTL file contains no data") | `test_empty_jtl_raises_error` |
| 3 | No rounds found for date | Return empty report with warning | `test_no_rounds_returns_empty_report` |
| 4 | Teams webhook timeout | Retry 3x then log failure, return partial result | `test_teams_webhook_timeout_retries` |
| 5 | Job stuck running >2h | Mark as timed out, terminal notification | `test_job_timeout_after_2_hours` |

- [ ] All 5 test cases listed
- [ ] Test functions will be written BEFORE implementation

---

### Step 6: Report Format Compliance (for generate_daily_report only)

- [ ] Per-run table has ALL columns: Label, # Samples, Average, Median, 90% Line, 95% Line, 99% Line, Min, Max, Error %, Throughput, Received KB/sec, Sent KB/sec
- [ ] Consolidated comparison table covers ALL rounds side by side
- [ ] Key Observations section has minimum 4 bullet points
- [ ] Recommendation section is a single actionable paragraph
- [ ] TOTAL row included in per-run table
- [ ] All response times in ms, throughput in req/s, bandwidth in KB/sec

---

### Step 7: Implementation Guidelines

- [ ] Implement in correct MCP tool (confirmed in Step 1)
- [ ] Use Pydantic models from Step 4
- [ ] Use try/except with logging (no bare except)
- [ ] Add timeout to all network calls (12 seconds)
- [ ] Add cache with TTL if parsing repeated data
- [ ] Clean up file handles in finally blocks
- [ ] Write failure tests BEFORE happy path implementation

---

## FEATURE TEMPLATE (Copy for each new feature)

```markdown
## Feature: [NAME]

### Architecture
- Tool: [start_test_execution | get_execution_status | generate_daily_report]
- Component: mcp-server/src/perf_mcp/server.py
- No 4th tool created: YES
- No SSH/remote execution: YES

### Security
- Hardcoded paths: NONE (all from env)
- Credentials: NONE
- Input validation: [DESCRIBE]

### Terminal Notifications
1. [TIMESTAMP] [ICON] [EVENT] — [DETAILS]
2. ...

### Pydantic Models
- Input: [MODEL_NAME] with fields [...]
- Output: [MODEL_NAME] with fields [...]

### Failure Scenarios
1. [SCENARIO] → [BEHAVIOR] → test_[name]()
2. ...

### Report Format (if applicable)
- [ ] All columns present
- [ ] All sections present
- [ ] Format matches mandated structure

### Status
- [ ] Tests written (happy + unhappy)
- [ ] Implementation complete
- [ ] Pre-commit audit passed
- [ ] Ready for review
```

---

## RED FLAGS — STOP IMMEDIATELY

| Red Flag | Correct Action |
|----------|----------------|
| About to create 4th MCP tool | Stop, refactor into existing tool |
| SSH or paramiko import | Remove, use UNC file share only |
| boto3 or cloud SDK import | Remove, use UNC file share only |
| Hardcoded `\\vm-hostname` | Replace with `os.environ["PERF_SHARED_ROOT"]` |
| Lifecycle event with no terminal print | Add print with timestamp and icon |
| JTL parsing without TOTAL row | Add aggregation for TOTAL row |
| Report missing "Average" column | Add Average column (it is required) |
| Cache without TTL | Add TTL + max size immediately |
| bare `except:` | Add `except Exception as e: logger.error(...)` |

---

**Version:** 1.0
**Created:** April 29, 2026
**Project:** Performance Test Execution & Reporting
