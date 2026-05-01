# Changelog

All notable changes to this project are documented in this file.

## [2026-04-29] - Shared Root Compatibility + Operational Hardening

### Changed
- Added VM-path compatible shared root handling in MCP server:
  - Accepts shared_root as either UNC path (\\server\\share) or VM drive path (L:\\...).
  - Resolves VM drive path to local UNC using PERF_SHARED_ROOT or PERF_SHARED_ROOT_UNC.
- Updated Pydantic validation models to support UNC and Windows drive-root formats.
- Updated test coverage for:
  - Windows drive shared_root acceptance.
  - Relative path rejection.
- Aligned runbook and architecture/governance documents with:
  - VM script path: L:\\Latest_Script_Sqlserver\\Xinsepect_RDS_SQL&BabelfishTestplan_Latest_07_21.jmx
  - VM shared root input: L:\\Testlogfiles\\MCP_Testlogfiles_entry
  - Local MCP UNC fallback requirement via PERF_SHARED_ROOT.

### Fixed
- Prevented local MCP filesystem operations from incorrectly treating VM-only drive paths as directly accessible.
- Improved validation error guidance when shared_root is VM-local and UNC fallback is not configured.

### Validation
- Test suite result: 66 passed, 1 warning.
- Commit pushed: 9a4f985

### Rollback
Use one of the following based on required impact:

1. Soft rollback (history preserved, new revert commit)
- Recommended for shared branches.
- Commands:

```powershell
git checkout main
git pull origin main
git revert --no-edit 9a4f985
git push origin main
```

2. Hard reset rollback (history rewritten)
- Use only if branch policy allows force push.
- Commands:

```powershell
git checkout main
git reset --hard e2bb689
git push --force-with-lease origin main
```

### Recovery Notes
- Baseline before this change: e2bb689
- Feature introduction commit: b235323
- Current compatibility commit: 9a4f985
- After rollback, re-run:

```powershell
.\\.venv\\Scripts\\python.exe -m pytest mcp-server/tests/ -q
```

## [2026-04-29] - Runbook Added

### Added
- Added detailed operational runbook for environment setup, MCP startup, test execution flow, and troubleshooting.

### Commit
- e2bb689

## [2026-04-29] - Initial MCP Implementation

### Added
- Introduced FastMCP server with three tools:
  - start_test_execution
  - get_execution_status
  - generate_daily_report
- Added JTL parsing, report generation, notification handling, and core test coverage.

### Commit
- b235323
