# AI Development Standards — Performance Test Execution & Reporting

**Purpose:** Non-negotiable quality rules for all AI-assisted development on this project.
**Audience:** AI agents, developers, code reviewers.
**Rule:** Every code change, every file, every commit must satisfy ALL rules below.

---

## RULE 1: Architecture Enforcement

**Standard:** Code must match the architecture diagram in `ARCHITECTURE.md` at all times.

**Requirements:**
- EXACTLY 3 MCP tools: `start_test_execution`, `get_execution_status`, `generate_daily_report`
- No 4th MCP tool under any circumstances
- MCP server is the ONLY component that reads JTL files and generates reports
- VM Runner is the ONLY component that executes JMeter
- MCP NEVER executes JMeter. VM Runner NEVER generates reports.
- Communication ONLY via Windows UNC shared folder — no SSH, no API, no cloud

**Red Flags:**
- 🚩 4th MCP tool being created
- 🚩 MCP server attempting to run JMeter directly
- 🚩 SSH or paramiko imports in MCP server
- 🚩 Any cloud storage client (boto3, azure-storage, etc.)
- 🚩 Logic placed in wrong component

**AI Response if violated:**
> "STOP: I am about to implement [ACTION] but architecture prohibits this. [REASON]. Requesting confirmation before proceeding."

---

## RULE 2: Report Format Compliance

**Standard:** Generated reports must EXACTLY match the mandated format. No creative formatting.

**Requirements:**
- Section 1: Per-run JMeter results table (Label, # Samples, Average, Median, 90%/95%/99% Line, Min, Max, Error%, Throughput, Received KB/sec, Sent KB/sec)
- Section 2: Consolidated comparison table (all rounds side by side with same metrics)
- Section 3: Key Observations (minimum 4 architect-level bullet points)
- Section 4: Recommendation (single paragraph, actionable)
- All response times in milliseconds
- Throughput in req/s
- Bandwidth in KB/sec
- Error rate as percentage with 2 decimal places

**Red Flags:**
- 🚩 Missing any column from the mandated table
- 🚩 Response times in wrong unit (seconds instead of ms)
- 🚩 Key Observations with fewer than 4 points
- 🚩 Missing TOTAL row in per-run table
- 🚩 Consolidated comparison missing any round

---

## RULE 3: Repository Hygiene

**Standard:** Zero tolerance for secrets, hardcoded paths, or temporary files in repository.

**Requirements:**
- `.env` file NEVER committed — always in `.gitignore`
- No UNC paths hardcoded: `\\vm-hostname\PerfTest` must come from `PERF_SHARED_ROOT` env var
- No webhook URLs in code
- No Windows user paths (C:\Users\...) in code
- `.gitignore` created before first commit, comprehensive

**Required `.gitignore` patterns:**
```gitignore
.env
.env.local
*.jtl
*.log
*.tmp
results/
__pycache__/
.venv/
*.egg-info/
dist/
build/
.pytest_cache/
Thumbs.db
.DS_Store
temp/
debug/
node_modules/
*.tsbuildinfo
```

**Red Flags:**
- 🚩 Hardcoded: `\\server\PerfTest\`
- 🚩 Hardcoded: `C:\Users\username\`
- 🚩 `.env` file in git status (unignored)
- 🚩 Real `.jtl` test files committed to repo
- 🚩 Webhook URL visible in any source file

---

## RULE 4: Cache Implementation Standards

**Standard:** Every cache must have TTL + max size + eviction policy.

**Requirements:**
- TTL minimum: 300 seconds for parsed JTL data
- Max entries: 64 per cache dict
- Eviction: LRU (OrderedDict with popitem)
- Thread-safe if used in async context
- Cache keys: SHA-256 of file path + modification timestamp (collision-resistant)

**Minimum Implementation:**
```python
import time
from collections import OrderedDict

CACHE_TTL_SECONDS = 300
CACHE_MAX_ENTRIES = 64
_jtl_cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()

def cache_get(key: str) -> Any | None:
    if key not in _jtl_cache:
        return None
    value, timestamp = _jtl_cache[key]
    if time.time() - timestamp > CACHE_TTL_SECONDS:
        del _jtl_cache[key]
        return None
    _jtl_cache.move_to_end(key)
    return value

def cache_set(key: str, value: Any) -> None:
    if len(_jtl_cache) >= CACHE_MAX_ENTRIES:
        _jtl_cache.popitem(last=False)
    _jtl_cache[key] = (value, time.time())
```

**Red Flags:**
- 🚩 `_cache: dict = {}` with no TTL or size limit
- 🚩 Cache growing unbounded until process restart

---

## RULE 5: Testing Requirements

**Standard:** Minimum 50% of tests must be unhappy path (failure/edge cases).

**Required happy path tests:**
- Valid 2-round same-day comparison
- Valid 3-round same-day comparison
- Single round (no comparison, report still generated)
- Teams notification successful delivery
- Slack notification successful delivery

**Required unhappy path tests:**
- Empty JTL file (0 rows)
- JTL with missing columns
- JTL with corrupt/malformed rows (partial parse)
- Day folder exists but has no completed rounds
- UNC path unreachable
- Teams webhook returns 429 (rate limit) — retry logic
- Teams webhook returns 500 — retry + fallback
- Job queued but VM runner never picks up (timeout after 2 hours)
- Concurrent job requests (same test_name same minute)
- Round folder exists but missing metadata.json

**Test naming convention:**
```python
def test_parse_valid_2_round_jtl():        # happy
def test_parse_empty_jtl_returns_error():  # unhappy
def test_report_with_single_round_no_comparison():  # edge
def test_teams_webhook_rate_limit_retries():  # unhappy
```

**Red Flags:**
- 🚩 Test file with only `test_valid_*` — missing unhappy path
- 🚩 No test for UNC path unavailable
- 🚩 No test for webhook failure retry

---

## RULE 6: Terminal Notification Compliance

**Standard:** Every lifecycle event MUST print to terminal with timestamp prefix.

**Required events (NONE may be silent):**
1. `[HH:MM:SS] 🚀 TEST EXECUTION STARTED`
2. `[HH:MM:SS] ✅ JOB QUEUED`
3. `[HH:MM:SS] ⏳ HEARTBEAT` (every 60 seconds while running)
4. `[HH:MM:SS] ✅ TEST COMPLETED`
5. `[HH:MM:SS] ❌ TEST FAILED`
6. `[HH:MM:SS] 📊 REPORTING STARTED`
7. `[HH:MM:SS] 📋 PARSED Round N`
8. `[HH:MM:SS] ✅ REPORT GENERATED`
9. `[HH:MM:SS] ✅ NOTIFICATION SENT`
10. `[HH:MM:SS] ❌ NOTIFICATION FAILED`

**Red Flags:**
- 🚩 Any lifecycle event that passes silently
- 🚩 Print without timestamp prefix
- 🚩 Using `logging.info()` instead of `print()` for terminal notifications (logging goes to log file, not terminal)

---

## RULE 7: Documentation Accuracy

**Standard:** Documentation must describe what the code actually does — no aspirational claims.

**Requirements:**
- Update CHANGELOG.md AFTER implementing, not before
- README Quick Start commands must work on a fresh machine
- All environment variables documented in README must be used in code
- Architecture diagram must match actual component boundaries
- Report format in docs must match HTML output exactly

**Red Flags:**
- 🚩 CHANGELOG mentions feature not yet implemented
- 🚩 README documents env var not used in code
- 🚩 Architecture diagram showing SSH connection (it does not exist in this project)

---

## BEST PRACTICES (Strongly Recommended)

### Error Handling
- Log errors with full context: file path, function name, input size, error type
- Return structured error JSON: `{"error": "...", "error_code": "...", "hint": "..."}`
- Include actionable hint in every error message
- Clean up file handles and resources in `finally` blocks

### Performance
- Stream large JTL files — do not load >50MB into memory at once
- Use pandas for JTL parsing (efficient for CSV with millions of rows)
- Generate HTML report using template string (no server-side rendering dependency)
- Webhook calls timeout after 12 seconds

### Security
- Validate UNC path format before use (prevent path traversal)
- Validate date format input (YYYY-MM-DD) with regex
- Validate test_name contains only alphanumeric, underscore, hyphen
- Validate script_path_on_vm is within allowed directory prefix (configurable via env)

---

## ENFORCEMENT CHECKLIST

### Before every feature implementation:
- [ ] Architecture placement confirmed (which of 3 tools?)
- [ ] Failure scenarios listed (minimum 5)
- [ ] Test cases for failures written first
- [ ] Report format compliance verified
- [ ] Terminal notifications planned

### Before every commit:
- [ ] No hardcoded paths or secrets
- [ ] No `.env` in staged files
- [ ] All new caches have TTL + max size
- [ ] Test suite still passes (all tests green)
- [ ] Documentation matches implementation

### Before release:
- [ ] All 7 rules verified with ✅
- [ ] README Quick Start works on fresh machine
- [ ] 10+ test runs of full end-to-end flow
- [ ] Stakeholder shown sample report for format approval

---

**Version:** 1.0
**Created:** April 29, 2026
**Project:** Performance Test Execution & Reporting
