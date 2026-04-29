# Before Each Git Commit — Performance Test Execution & Reporting

**Purpose:** Mandatory audit before every commit. AI runs this automatically. Engineers run before PR.
**Rule:** Do NOT commit if any section shows ❌. Fix all violations first.

---

## SECTION 1: Repository Hygiene

### 1.1 Secrets and Credentials Scan

```powershell
# Run in project root
Select-String -Path ".\mcp-server\src\**\*.py" -Pattern "(api_key|password|token|webhook|secret)\s*=\s*[`"']" -Recurse
Select-String -Path ".\vm-runner\**\*.ps1" -Pattern "(password|credential|secret)\s*=" -Recurse
```

**Expected:** No matches (or only test fixtures with fake data)

**Check also:**
- [ ] No `TEAMS_WEBHOOK_URL=https://...` in any `.py` or `.ps1` file
- [ ] No `SLACK_WEBHOOK_URL=https://...` in any `.py` or `.ps1` file
- [ ] No VM IP addresses or hostnames hardcoded

---

### 1.2 Hardcoded Path Scan

```powershell
# Must find ZERO matches
Select-String -Path ".\mcp-server\src\**\*.py" -Pattern "\\\\[a-zA-Z]" -Recurse
Select-String -Path ".\mcp-server\src\**\*.py" -Pattern "C:\\\\Users\\" -Recurse
```

**Expected:** Zero matches. All UNC paths come from `os.environ["PERF_SHARED_ROOT"]`

---

### 1.3 .env File Not Staged

```powershell
git status --short | Where-Object { $_ -match "\.env" }
```

**Expected:** No `.env` file in staged or untracked list.

---

### 1.4 JTL Test Files Not Staged

```powershell
git status --short | Where-Object { $_ -match "\.jtl" }
```

**Expected:** No `.jtl` files committed (they contain real test data and can be large).

---

## SECTION 2: Architecture Compliance

### 2.1 Tool Count Verification

```powershell
# Count @mcp.tool() decorators in server.py
Select-String -Path ".\mcp-server\src\perf_mcp\server.py" -Pattern "@mcp\.tool\(\)"
```

**Expected:** EXACTLY 3 matches:
- `start_test_execution`
- `get_execution_status`
- `generate_daily_report`

**Fail if:** 2 or fewer (missing tool), 4 or more (architectural violation).

---

### 2.2 SSH / Remote Execution Scan

```powershell
Select-String -Path ".\mcp-server\src\**\*.py" -Pattern "(paramiko|fabric|invoke|ssh|subprocess.*ssh)" -Recurse
```

**Expected:** Zero matches. MCP never executes remote commands.

---

### 2.3 Cloud Storage Scan

```powershell
Select-String -Path ".\mcp-server\src\**\*.py" -Pattern "(boto3|azure\.storage|google\.cloud|s3\.put|blob\.upload)" -Recurse
```

**Expected:** Zero matches. All storage is UNC file share.

---

## SECTION 3: Code Quality

### 3.1 Silent Exception Check

```powershell
Select-String -Path ".\mcp-server\src\**\*.py" -Pattern "except:\s*$|except Exception:\s*$" -Recurse
```

**Expected:** Zero bare `except:` blocks. Every exception must log with context.

---

### 3.2 Cache TTL Check

```powershell
# Find all cache dicts
Select-String -Path ".\mcp-server\src\**\*.py" -Pattern "OrderedDict|_cache" -Recurse
```

**For every cache found, verify:**
- [ ] Has TTL check: `time.time() - timestamp > CACHE_TTL_SECONDS`
- [ ] Has max size: `if len(_cache) >= CACHE_MAX_ENTRIES`
- [ ] Has LRU eviction: `_cache.popitem(last=False)`

---

### 3.3 Terminal Notification Check

```powershell
# Verify print statements exist for key events
Select-String -Path ".\mcp-server\src\**\*.py" -Pattern "print\(f\"\[" -Recurse
```

**Verify these events are present in server.py:**
- [ ] `TEST EXECUTION STARTED` or `JOB QUEUED`
- [ ] `HEARTBEAT`
- [ ] `TEST COMPLETED`
- [ ] `TEST FAILED`
- [ ] `REPORTING STARTED`
- [ ] `PARSED Round`
- [ ] `REPORT GENERATED`
- [ ] `NOTIFICATION SENT` or `NOTIFICATION FAILED`

---

### 3.4 Report Format Compliance

Manually verify `generate_daily_report` produces HTML with:
- [ ] Per-run table with columns: Label, # Samples, Average, Median, 90% Line, 95% Line, 99% Line, Min, Max, Error %, Throughput, Received KB/sec, Sent KB/sec
- [ ] TOTAL row in per-run table
- [ ] Consolidated comparison table with all rounds
- [ ] Key Observations section (minimum 4 bullet points)
- [ ] Recommendation section (single paragraph)

---

## SECTION 4: Testing

### 4.1 Count Test Types

```powershell
# Happy path tests
Select-String -Path ".\tests\**\*.py" -Pattern "def test_.*valid|def test_.*success|def test_.*parse.*jtl\b" -Recurse | Measure-Object

# Unhappy path tests
Select-String -Path ".\tests\**\*.py" -Pattern "def test_.*error|def test_.*fail|def test_.*invalid|def test_.*timeout|def test_.*empty|def test_.*missing" -Recurse | Measure-Object
```

**Expected ratio:** At least 50% unhappy path tests.

---

### 4.2 Run Test Suite

```powershell
cd mcp-server
.\.venv\Scripts\Activate.ps1
python -m pytest tests/ -v --tb=short
```

**Expected:** All tests PASS. Exit code 0.
**Blocking condition:** Any failing test → do NOT commit.

---

### 4.3 Required Test Coverage Check

Verify these specific test cases exist:
- [ ] `test_parse_empty_jtl_raises_error`
- [ ] `test_parse_malformed_jtl_handles_gracefully`
- [ ] `test_single_round_no_comparison_still_generates_report`
- [ ] `test_two_round_comparison_calculates_correct_deltas`
- [ ] `test_three_round_comparison_all_pairs_and_first_last`
- [ ] `test_unc_path_unavailable_raises_value_error`
- [ ] `test_teams_webhook_failure_retries_3_times`
- [ ] `test_job_timeout_after_2_hours`

---

## SECTION 5: Documentation

### 5.1 README Accuracy

- [ ] `PERF_SHARED_ROOT` env var documented and used in code
- [ ] `TEAMS_WEBHOOK_URL` env var documented and used in code
- [ ] `SLACK_WEBHOOK_URL` env var documented and used in code
- [ ] `NOTIFICATION_CHANNEL` env var documented and used in code
- [ ] VM runner setup instructions accurate
- [ ] Quick Start commands tested on fresh terminal

---

### 5.2 CHANGELOG Accuracy

For every claim in CHANGELOG.md:
- [ ] Verify the feature exists in code
- [ ] Verify it behaves as described
- [ ] Remove claims for features not yet implemented

---

## AUDIT REPORT TEMPLATE

AI must provide this before code review:

```
## Pre-Commit Audit Report — [DATE]

### 1. Repository Hygiene
- [✅/❌] Secrets scan: [RESULT]
- [✅/❌] Hardcoded paths: [RESULT]
- [✅/❌] .env not staged: [RESULT]
- [✅/❌] No .jtl files staged: [RESULT]

### 2. Architecture Compliance
- [✅/❌] Tool count = 3: [RESULT]
- [✅/❌] No SSH/remote execution: [RESULT]
- [✅/❌] No cloud storage: [RESULT]

### 3. Code Quality
- [✅/❌] No bare except: [RESULT]
- [✅/❌] All caches have TTL: [RESULT]
- [✅/❌] All terminal notifications present: [RESULT]
- [✅/❌] Report format compliant: [RESULT]

### 4. Testing
- [✅/❌] Test ratio (happy/unhappy): [X/Y = Z%]
- [✅/❌] All tests passing: [RESULT]
- [✅/❌] Required tests exist: [RESULT]

### 5. Documentation
- [✅/❌] README env vars accurate: [RESULT]
- [✅/❌] CHANGELOG claims verified: [RESULT]

---
VIOLATIONS FOUND: [N]
[List each with fix applied]

READY FOR REVIEW: [YES / NO]
```

---

## BLOCKING CONDITIONS — DO NOT COMMIT IF ANY APPLY

| Condition | Reason |
|-----------|--------|
| `.env` file staged | Credential leak |
| Hardcoded UNC path | Breaks on other machines |
| 4th MCP tool present | Architecture violation |
| SSH import in MCP server | Architecture violation |
| Cloud storage import | Architecture violation |
| Any test failing | Broken functionality |
| Bare `except:` block | Silent failures in production |
| Cache without TTL | Memory leak |
| Terminal notification missing for any lifecycle event | Silent execution |
| Report HTML missing mandated columns | Stakeholder report unacceptable |

---

**Version:** 1.0
**Created:** April 29, 2026
**Project:** Performance Test Execution & Reporting
