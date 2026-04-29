# AI Collaboration Guide — Performance Test Execution & Reporting

**Purpose:** How to work effectively with AI assistants on this project.
**Audience:** Engineers managing AI-assisted development on performance testing tooling.

---

## Core Principle

**AI will build what you ask for, but will not automatically enforce production standards unless they are defined upfront.**

This project has strict constraints (3 MCP tools only, no cloud storage, no VM credentials, mandatory terminal notifications, strict report format). AI must read `copilot-instructions.md` and `AI_DEVELOPMENT_STANDARDS.md` before starting any work.

---

## Setup Phase: Training AI Before Starting Work

### Step 1: Share Standards Documents

At the start of every session, confirm AI has read:

```
1. .github/copilot-instructions.md       ← PRIMARY — read this first
2. ARCHITECTURE.md                       ← Component boundaries
3. TRD.md                                ← Full requirements
4. .github/AI_DEVELOPMENT_STANDARDS.md  ← 7 non-negotiable rules
5. .github/BEFORE_EACH_FEATURE.md       ← Pre-implementation checklist
6. .github/BEFORE_EACH_COMMIT.md        ← Pre-commit audit checklist
```

### Step 2: Establish Red Flags for This Project

Tell AI to STOP and ask before:

```
🚩 Creating a 4th MCP tool
🚩 Using SSH, paramiko, or remote execution from MCP
🚩 Importing boto3, azure-storage, or any cloud SDK
🚩 Hardcoding \\vm-hostname\PerfTest path
🚩 Generating report in any format other than mandated 4-section format
🚩 Skipping any terminal notification event
🚩 Touching JMeter parameterization CSV files
```

---

## Communication Patterns

### Assigning Work to AI

**Bad (too vague):**
> "Implement the report generation"

**Good (specific with constraints):**
```
Feature: generate_daily_report MCP tool

Architecture placement:
- Implement as @mcp.tool() in mcp-server/src/perf_mcp/server.py
- Tool scans shared folder for YYYY-MM-DD_Round* folders
- Parses each results.jtl (CSV format)
- Compares consecutive rounds AND first-vs-last
- Generates HTML report in mandated 4-section format
- Sends Teams/Slack notification if NOTIFICATION_CHANNEL env set
- ALL notifications to terminal regardless of channel setting

Before implementing:
- Show me the Pydantic input/output schema
- List 5 ways this could fail
- Confirm report format matches copilot-instructions.md

Confirm you understand, then run BEFORE_EACH_FEATURE.md checklist.
```

### Catching Architecture Violations

Ask regularly:
```
Question: Which component reads the JTL file and generates the HTML report?
Expected: "MCP server (generate_daily_report tool)"

Question: Which component executes JMeter?
Expected: "VM PowerShell runner — MCP never executes JMeter"

Question: How many MCP tools exist?
Expected: "Exactly 3"

If answer differs → Architecture violation → Fix before proceeding.
```

---

## Common Failure Modes for This Project

### Failure 1: Scope Creep — Adding a 4th MCP Tool

**Problem:** AI decides to add `parse_jtl()` or `compare_rounds()` as separate MCP tools.

**Prevention:**
```
Rule: generate_daily_report internally handles parsing, comparison,
      and report generation. No standalone parsing tool allowed.
```

### Failure 2: Cloud Storage Suggestion

**Problem:** AI suggests using S3 or Azure Blob for storing results.

**Prevention:**
```
Rule: All storage is Windows UNC file share.
      PERF_SHARED_ROOT env var holds the UNC path.
      Never suggest or implement cloud storage.
```

### Failure 3: Wrong Report Format

**Problem:** AI generates a summary that does not include the mandated table columns.

**Prevention:**
```
Rule: Report must exactly match Section 1-4 format in copilot-instructions.md.
      Verify column headers match before generating HTML.
      "Average" column is AVERAGE RESPONSE TIME in ms — never omit this.
```

### Failure 4: Silent Terminal

**Problem:** MCP tool runs but terminal shows no progress.

**Prevention:**
```
Rule: Every lifecycle event prints to terminal with timestamp.
      Heartbeat every 60 seconds during test execution.
      No silent operations allowed.
```

### Failure 5: VM Credential Leak

**Problem:** AI asks for or stores VM username/password to enable remote execution.

**Prevention:**
```
Rule: MCP never connects to VM. Period.
      VM runner is started manually by engineer on VM.
      MCP only reads/writes to shared folder.
```

---

## Pre-Feature Checkpoint Questions

Before approving any feature implementation, ask:

1. "Which of the 3 MCP tools does this feature belong to?"
2. "Will this touch JMeter CSV parameterization files?" (answer must be NO)
3. "Show me the terminal notification events this feature emits."
4. "Show me the Pydantic model for this tool's input and output."
5. "List 5 ways this could fail and your test cases for each."

---

## Pre-Commit Checkpoint Questions

Before approving any commit, ask:

1. "Run BEFORE_EACH_COMMIT.md audit. Give me ✅/❌ for each section."
2. "Are any hardcoded UNC paths in the diff?"
3. "Does the report HTML output match the mandated format?"
4. "How many happy path tests vs unhappy path tests?"

**Expected AI Response:**
```
Pre-Commit Audit:
✅ No hardcoded paths
✅ No secrets in code
✅ .env in .gitignore
✅ All caches have TTL
✅ Terminal notifications in all lifecycle events
✅ Report format matches mandated 4-section structure
✅ Tests: 8 happy / 11 unhappy (58% unhappy)
✅ Architecture: All 3 tools in correct component
✅ Documentation matches implementation
READY FOR REVIEW: YES
```

---

## Success Metrics

You are collaborating well when:
- AI stops before creating a 4th MCP tool and asks for confirmation
- AI verifies report format columns against `copilot-instructions.md` before generating HTML
- AI runs BEFORE_EACH_FEATURE and BEFORE_EACH_COMMIT automatically
- Terminal always shows lifecycle events during test execution
- No VM credentials appear anywhere in code

You are struggling when:
- Report is missing columns or in wrong format
- Terminal is silent during test execution
- Cloud storage imports appear in code
- Test suite has only happy path tests

---

**Version:** 1.0
**Created:** April 29, 2026
**Project:** Performance Test Execution & Reporting
