"""
FastMCP server — Performance Test Execution & Reporting.

Exposes EXACTLY 3 MCP tools (architectural constraint — never add a 4th):
  1. start_test_execution   — queue job, monitor execution, trigger report
  2. get_execution_status   — return current job state with metrics
  3. generate_daily_report  — scan results folder, compare rounds, generate HTML

Communication with VM is entirely via Windows UNC file share.
No SSH. No credentials in code. All secrets from environment variables.

Security:
  - test_name validated: alphanumeric + _ + - only (NFR-003-5)
  - script_path_on_vm validated against ALLOWED_VM_SCRIPT_PREFIX (NFR-003-6)
  - UNC path format validated before use (NFR-003-4)
  - No secrets logged (NFR-003-3)
"""

from __future__ import annotations

import glob
import io
import json
import logging
import os
import random
import re
import string
import subprocess
import sys
import threading
import time
from datetime import datetime, date as date_cls
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from .jtl_parser import find_jtl_file, parse_jtl
from .models import (
    GenerateDailyReportInput,
    GenerateDailyReportOutput,
    GetExecutionStatusInput,
    GetExecutionStatusOutput,
    HeartbeatEntry,
    JobQueueEntry,
    KpiMetrics,
    RunMetadata,
    RoundSummary,
    StartTestExecutionInput,
    StartTestExecutionOutput,
)
from .notifier import send_report_notification
from .report_generator import generate_html_report

# Load .env from mcp-server directory (safe — file is in .gitignore)
load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

mcp = FastMCP("perf-mcp")

# Monitoring constants
_HEARTBEAT_INTERVAL_SECONDS = 60
_JOB_TIMEOUT_MINUTES = 120
_LIVE_LOG_TAIL_LINES = 100
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_CLIENT_CONNECTED_ANNOUNCED = False


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _ts() -> str:
    """Return [HH:MM:SS] timestamp string for terminal notifications."""
    return datetime.now().strftime("%H:%M:%S")


def _git_pull(repo_path: Path) -> None:
    """Pull latest changes from GitHub (git transport mode). Non-fatal on failure."""
    try:
        result = subprocess.run(
            ["git", "pull", "--rebase"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("git pull non-zero exit: %s", result.stderr.strip())
    except Exception as exc:
        logger.warning("git pull skipped (non-fatal): %s", exc)


def _git_push(repo_path: Path, message: str) -> None:
    """Stage all changes, commit, and push to GitHub. Non-fatal on failure."""
    try:
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(repo_path),
            capture_output=True,
            timeout=15,
        )
        commit = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=15,
        )
        # Only skip push if there was genuinely nothing to commit
        nothing_to_commit = (
            "nothing to commit" in commit.stdout
            or "nothing to commit" in commit.stderr
        )
        if nothing_to_commit:
            logger.info("git commit: nothing to commit for '%s'", message)
            return
        if commit.returncode != 0:
            logger.warning("git commit failed (rc=%d): %s | %s", commit.returncode, commit.stdout.strip(), commit.stderr.strip())
            _notify(f"[{_ts()}] ⚠️  GIT COMMIT FAILED — rc={commit.returncode} | {commit.stderr.strip()[:120]}")
            return
        _notify(f"[{_ts()}] 📋 GIT COMMITTED — {message}")
        push = subprocess.run(
            ["git", "push"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if push.returncode != 0:
            logger.warning("git push failed: %s", push.stderr.strip())
            _notify(f"[{_ts()}] ⚠️  GIT PUSH FAILED — {push.stderr.strip()[:120]}")
        else:
            _notify(f"[{_ts()}] ✅ GIT PUSHED — {message}")
    except Exception as exc:
        logger.warning("git push skipped (non-fatal): %s", exc)
        _notify(f"[{_ts()}] ⚠️  GIT PUSH SKIPPED — {exc}")


def _notify(msg: str) -> None:
    """Write a terminal notification line to stderr using UTF-8 encoding.

    Writes to stderr to avoid interfering with stdio JSON-RPC transport on stdout,
    and forces UTF-8 to avoid charmap errors on Windows for emoji characters.
    """
    try:
        sys.stderr.buffer.write((msg + "\n").encode("utf-8", errors="replace"))
        sys.stderr.buffer.flush()
    except AttributeError:
        # Fallback for streams without a buffer (e.g., StringIO in tests)
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()


def _notify_waiting_for_client() -> None:
    """Emit startup status indicating server is ready and waiting for an MCP client.

    Writes to stderr to avoid interfering with stdio JSON-RPC transport on stdout.
    """
    _notify(f"[{_ts()}] 🚀 MCP STARTED — Waiting for MCP client to connect")


def _notify_client_connected_once() -> None:
    """Emit one-time status when the first MCP tool request is received.

    The first tool invocation confirms client-session connectivity.
    """
    global _CLIENT_CONNECTED_ANNOUNCED
    if _CLIENT_CONNECTED_ANNOUNCED:
        return
    _CLIENT_CONNECTED_ANNOUNCED = True
    _notify(f"[{_ts()}] ✅ MCP CLIENT CONNECTED — First tool request received")


def _generate_job_id(test_name: str) -> str:
    """Generate a unique job ID: HH-MM-SS_testName_XXXXXX.

    Args:
        test_name: Logical test name (already validated).

    Returns:
        Unique job identifier string.
    """
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{datetime.now().strftime('%H-%M-%S')}_{test_name}_{suffix}"


def _count_rounds_for_today(results_dir: Path) -> int:
    """Count existing Round folders for today to determine next round number.

    Args:
        results_dir: Path to the results directory under shared_root.

    Returns:
        Next round number (existing count + 1).
    """
    today = date_cls.today().isoformat()
    pattern = str(results_dir / f"{today}_Round*")
    existing = glob.glob(pattern)
    return len(existing) + 1


def _validate_script_path(script_path: str) -> None:
    """Validate VM script path against ALLOWED_VM_SCRIPT_PREFIX env var (NFR-003-6).

    Args:
        script_path: Path to JMX script on VM.

    Raises:
        ValueError: If path does not start with the allowed prefix.
    """
    allowed_prefix = os.getenv("ALLOWED_VM_SCRIPT_PREFIX", "")
    if allowed_prefix and not script_path.startswith(allowed_prefix):
        raise ValueError(
            f"script_path_on_vm '{script_path}' is not under the allowed prefix '{allowed_prefix}'. "
            "Update ALLOWED_VM_SCRIPT_PREFIX in .env if you need to use a different path."
        )


def _resolve_local_shared_root(shared_root: str) -> str:
    """Resolve shared_root to a local-accessible path for MCP file operations.

    If input is a VM-local drive path (e.g., L:\\...), local MCP cannot access it
    directly. In that case, this function requires UNC fallback from environment:
    ``PERF_SHARED_ROOT`` or ``PERF_SHARED_ROOT_UNC``.

    Args:
        shared_root: Requested shared root from MCP tool input.

    Returns:
        A path accessible from the local MCP machine (normally UNC).

    Raises:
        ValueError: If shared_root is VM-local drive path and no UNC fallback is set.
    """
    if shared_root.startswith("\\\\") or shared_root.startswith("//"):
        return shared_root

    if _WINDOWS_DRIVE_RE.match(shared_root):
        # If PERF_SHARED_ROOT is set to a drive path (MCP running on VM), use directly
        fallback = os.getenv("PERF_SHARED_ROOT") or os.getenv("PERF_SHARED_ROOT_UNC")
        if fallback and _WINDOWS_DRIVE_RE.match(fallback):
            _notify(
                f"[{_ts()}] ✅  SHARED_ROOT_VM — Running on VM, using local drive path '{fallback}' directly"
            )
            return fallback
        if fallback and (fallback.startswith("\\\\") or fallback.startswith("//")):
            _notify(
                f"[{_ts()}] ⚠️  SHARED_ROOT_MAP — VM path '{shared_root}' mapped to local UNC '{fallback}'"
            )
            return fallback
        # No fallback set — if path is directly accessible (MCP on VM), use as-is
        if Path(shared_root).exists():
            return shared_root
        raise ValueError(
            "shared_root is VM-local drive path and is not accessible from local MCP. "
            "Set PERF_SHARED_ROOT (or PERF_SHARED_ROOT_UNC) to the UNC equivalent, "
            "for example \\\\host\\share\\MCP_Testlogfiles_entry."
        )

    return shared_root


def _read_json_file(path: Path) -> dict[str, Any] | None:
    """Read and parse a JSON file, returning None on any error.

    Args:
        path: Path to JSON file.

    Returns:
        Parsed dict or None if file is missing/unreadable/corrupt.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        logger.warning("JSON parse error in '%s': %s", path, exc)
        return None
    except OSError as exc:
        logger.warning("Cannot read '%s': %s", path, exc)
        return None


def _tail_log_file(log_path: Path, last_position: int) -> tuple[list[str], int]:
    """Read new lines from a live log file since the last read position.

    Handles the case where the file is temporarily unavailable (UNC share lag).

    Args:
        log_path: Path to runner_live.log.
        last_position: Byte offset from the previous read (0 for first read).

    Returns:
        Tuple of (new_lines list, new_position). Returns ([], last_position) on error.
    """
    try:
        size = log_path.stat().st_size
        if size < last_position:
            # File was truncated or recreated — reset position
            logger.debug("Live log appears truncated; resetting read position for %s", log_path)
            last_position = 0
        if size == last_position:
            return [], last_position
        with log_path.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(last_position)
            lines = fh.readlines()
            new_position = fh.tell()
        return [l.rstrip("\n\r") for l in lines if l.strip()], new_position
    except FileNotFoundError:
        return [], last_position
    except OSError as exc:
        logger.debug("Live log temporarily unavailable (%s): %s", log_path, exc)
        return [], last_position


def _discover_round_folders(results_dir: Path, report_date: str, test_name_filter: str | None) -> list[Path]:
    """Discover result folders for a given date using artifact-based detection.

    Supports both standard naming (YYYY-MM-DD_RoundN_HH-MM-SS) and
    historical non-standard folder names (FR-004-2).

    Args:
        results_dir: results/ directory under shared_root.
        report_date: Date string in YYYY-MM-DD format.
        test_name_filter: Optional test name to filter by (from metadata.json).

    Returns:
        List of matching result folder Paths, sorted by round number then folder name.
    """
    found: list[Path] = []

    if not results_dir.exists():
        return found

    for folder in sorted(results_dir.iterdir()):
        if not folder.is_dir():
            continue

        # Primary: standard naming convention
        is_standard_date = folder.name.startswith(report_date)

        # Fallback: artifact-based detection for non-standard names
        jtl_files = list(folder.glob("*.jtl"))
        metadata_path = folder / "metadata.json"
        has_artifacts = bool(jtl_files) and metadata_path.exists()

        if not is_standard_date and not has_artifacts:
            continue

        # For non-standard folders, verify metadata timestamp matches the requested date
        if not is_standard_date and has_artifacts:
            meta = _read_json_file(metadata_path)
            if meta is None:
                continue
            started_at = meta.get("started_at", "")
            if not started_at.startswith(report_date):
                continue

        # Apply test name filter if provided
        if test_name_filter:
            meta = _read_json_file(metadata_path)
            if meta and meta.get("test_name", "") != test_name_filter:
                continue

        if has_artifacts or jtl_files:
            found.append(folder)

    return found


def _kpi_from_summary(summary: dict[str, Any]) -> KpiMetrics | None:
    """Parse KpiMetrics from a summary.json dict.

    Args:
        summary: Parsed summary.json dict.

    Returns:
        :class:`KpiMetrics` if all required fields present, else None.
    """
    try:
        return KpiMetrics(
            total_requests=summary["total_requests"],
            successful_requests=summary.get("successful_requests", summary["total_requests"] - summary.get("failed_requests", 0)),
            failed_requests=summary.get("failed_requests", 0),
            error_rate_pct=summary["error_rate_pct"],
            avg_response_ms=summary["avg_response_ms"],
            median_ms=summary["median_ms"],
            p90_ms=summary["p90_ms"],
            p95_ms=summary["p95_ms"],
            p99_ms=summary["p99_ms"],
            min_ms=summary["min_ms"],
            max_ms=summary["max_ms"],
            throughput_req_sec=summary["throughput_req_sec"],
            received_kb_sec=summary.get("received_kb_sec", 0.0),
            sent_kb_sec=summary.get("sent_kb_sec", 0.0),
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Incomplete summary.json — cannot build KpiMetrics: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Tool 1: start_test_execution
# ---------------------------------------------------------------------------


@mcp.tool()
def start_test_execution(
    test_name: str,
    script_path_on_vm: str,
    shared_root: str,
    notification_channel: str = "terminal",
) -> dict[str, Any]:
    """Queue a JMeter test job on the remote VM and monitor execution to completion.

    Validates inputs, writes a job JSON to the UNC __QUEUE__ folder, then enters
    a monitoring loop that tails runner_live.log for live VM output and falls back
    to heartbeat-only monitoring if the live log is unavailable. On completion,
    automatically invokes generate_daily_report.

    Args:
        test_name: Logical test name (alphanumeric, underscores, hyphens, max 100 chars).
        script_path_on_vm: Absolute path to JMX script on VM. Must match
            ``ALLOWED_VM_SCRIPT_PREFIX`` environment variable.
        shared_root: UNC path or VM-local drive path (e.g. ``L:\\Testlogfiles\\MCP_Testlogfiles_entry``).
        notification_channel: One of ``terminal`` | ``teams`` | ``slack`` | ``both``.

    Returns:
        Dict matching :class:`StartTestExecutionOutput` schema with job_id, round,
        status, result_folder, and monitoring_mode.

    Raises:
        ValueError: On input validation failure.

    Example:
        >>> result = start_test_execution(
        ...     test_name="GET_RO_Number_Load",
        ...     script_path_on_vm="L:\\\\Latest_Script_Sqlserver\\\\Xinsepect_RDS_SQL&BabelfishTestplan_Latest_07_21.jmx",
        ...     shared_root="L:\\\\Testlogfiles\\\\MCP_Testlogfiles_entry",
        ...     notification_channel="terminal",
        ... )
    """
    _notify_client_connected_once()

    # --- Input validation ---
    try:
        inp = StartTestExecutionInput(
            test_name=test_name,
            script_path_on_vm=script_path_on_vm,
            shared_root=shared_root,
            notification_channel=notification_channel,
        )
    except Exception as exc:
        logger.error("start_test_execution input validation failed: %s", exc)
        return {"error": str(exc), "status": "validation_failed"}

    try:
        _validate_script_path(inp.script_path_on_vm)
    except ValueError as exc:
        logger.error("Script path validation failed: %s", exc)
        return {"error": str(exc), "status": "validation_failed"}

    try:
        local_shared_root = _resolve_local_shared_root(inp.shared_root)
    except ValueError as exc:
        logger.error("Shared root resolution failed: %s", exc)
        return {"error": str(exc), "status": "validation_failed"}

    shared = Path(local_shared_root)
    results_dir = shared / "results"
    queue_dir = shared / os.getenv("JOB_QUEUE_DIR", "__QUEUE__")

    # --- Generate job identity ---
    job_id = _generate_job_id(inp.test_name)
    round_number = _count_rounds_for_today(results_dir)
    today = date_cls.today().isoformat()
    time_suffix = datetime.now().strftime("%H-%M-%S")
    day_folder = f"{today}_Round{round_number}_{time_suffix}"
    result_folder = results_dir / day_folder
    live_log_path = result_folder / "runner_live.log"

    # --- Write job JSON to queue ---
    job = JobQueueEntry(
        job_id=job_id,
        test_name=inp.test_name,
        script_path_on_vm=inp.script_path_on_vm,
        round=round_number,
        day_folder=day_folder,
        created_at=datetime.now().isoformat(),
        notification_channel=inp.notification_channel,
    )

    try:
        queue_dir.mkdir(parents=True, exist_ok=True)
        job_file = queue_dir / f"{job_id}.json"
        job_file.write_text(job.model_dump_json(indent=2), encoding="utf-8")
    except OSError as exc:
        logger.error("Failed to write job file to queue '%s': %s", queue_dir, exc, exc_info=True)
        return {"error": f"Failed to write job to queue: {exc}", "status": "queue_failed"}

    # Push job to GitHub so VM runner can pull and pick it up
    _git_push(shared, f"job: {job_id}")

    _notify(
        f"[{_ts()}] ✅ JOB QUEUED — Job: {job_id} | Round: {round_number} | Folder: {day_folder}"
    )
    _notify(
        f"[{_ts()}] 🚀 TEST EXECUTION STARTED — Script: {inp.script_path_on_vm} | "
        f"Waiting for VM runner to pick up job..."
    )

    # --- Monitoring loop ---
    monitoring_mode = "heartbeat_only"
    start_time = time.monotonic()
    elapsed_min = 0
    live_log_pos = 0
    live_log_warned = False
    final_status = "queued"

    while True:
        elapsed_sec = time.monotonic() - start_time
        elapsed_min = int(elapsed_sec // 60)

        # Timeout guard
        if elapsed_min >= _JOB_TIMEOUT_MINUTES:
            _notify(f"[{_ts()}] ❌ JOB TIMED OUT — Elapsed: {_JOB_TIMEOUT_MINUTES} min | Job: {job_id}")
            logger.error("Job timed out after %d minutes: %s", _JOB_TIMEOUT_MINUTES, job_id)
            final_status = "timed_out"
            break

        # Pull latest results from GitHub before checking status
        _git_pull(shared)

        # Read metadata.json for status
        meta_path = result_folder / "metadata.json"
        meta_data = _read_json_file(meta_path)
        current_status = meta_data.get("status", "queued") if meta_data else "queued"

        # Attempt live log tailing
        new_lines, live_log_pos = _tail_log_file(live_log_path, live_log_pos)
        if new_lines:
            monitoring_mode = "live_stream"
            live_log_warned = False
            for line in new_lines[-_LIVE_LOG_TAIL_LINES:]:
                _notify(f"[{_ts()}] 📋 VM_STREAM — {line}")
        else:
            if monitoring_mode == "live_stream":
                # Log stream interrupted — switch to fallback
                monitoring_mode = "heartbeat_only"
                if not live_log_warned:
                    _notify(
                        f"[{_ts()}] ⚠️  MONITORING_FALLBACK — "
                        "Live log temporarily unavailable; heartbeat-only mode active"
                    )
                    live_log_warned = True

        if current_status == "completed":
            # Read completion metrics
            summary_data = _read_json_file(result_folder / "summary.json")
            if summary_data:
                metrics = _kpi_from_summary(summary_data)
                if metrics:
                    _notify(
                        f"[{_ts()}] ✅ TEST COMPLETED — "
                        f"Requests: {metrics.total_requests:,} | "
                        f"Errors: {metrics.error_rate_pct:.2f}% | "
                        f"Avg: {metrics.avg_response_ms:.0f}ms"
                    )
                else:
                    _notify(f"[{_ts()}] ✅ TEST COMPLETED — Job: {job_id}")
            else:
                _notify(f"[{_ts()}] ✅ TEST COMPLETED — Job: {job_id}")
            final_status = "completed"
            break

        elif current_status == "failed":
            error_msg = meta_data.get("error_message", "Unknown error") if meta_data else "No metadata"
            _notify(f"[{_ts()}] ❌ TEST FAILED — Error: {error_msg} | Folder: {result_folder}")
            logger.error("Job failed: %s | Error: %s", job_id, error_msg)
            final_status = "failed"
            break

        # Heartbeat every 60 seconds
        _notify(
            f"[{_ts()}] ⏳ HEARTBEAT — Elapsed: {elapsed_min} min | "
            f"Status: {current_status.upper()} | VM Runner active"
        )
        time.sleep(_HEARTBEAT_INTERVAL_SECONDS)

    # --- Auto-trigger report on successful completion ---
    if final_status == "completed":
        _auto_generate_report(
            shared_root=local_shared_root,
            date=today,
            notification_channel=inp.notification_channel,
        )

    output = StartTestExecutionOutput(
        job_id=job_id,
        round=round_number,
        day_folder=day_folder,
        status=final_status,
        result_folder=str(result_folder),
        live_log_path=str(live_log_path),
        monitoring_mode=monitoring_mode,
    )
    return output.model_dump()


# ---------------------------------------------------------------------------
# Tool 2: get_execution_status
# ---------------------------------------------------------------------------


@mcp.tool()
def get_execution_status(job_id: str, shared_root: str) -> dict[str, Any]:
    """Return the current execution status and KPIs for a given job.

    Scans all queue and result folders for the job_id, reads metadata.json
    and summary.json if available, and prints status to terminal.

    Args:
        job_id: Unique job identifier returned by start_test_execution.
        shared_root: UNC path or VM-local drive path (same value used at job creation).

    Returns:
        Dict matching :class:`GetExecutionStatusOutput` schema.

    Example:
        >>> status = get_execution_status(
        ...     job_id="14-30-22_GET_RO_Number_abc123",
        ...     shared_root="L:\\\\Testlogfiles\\\\MCP_Testlogfiles_entry",
        ... )
    """
    _notify_client_connected_once()

    try:
        inp = GetExecutionStatusInput(job_id=job_id, shared_root=shared_root)
    except Exception as exc:
        logger.error("get_execution_status input validation failed: %s", exc)
        return {"error": str(exc), "status": "validation_failed"}

    try:
        local_shared_root = _resolve_local_shared_root(inp.shared_root)
    except ValueError as exc:
        logger.error("Shared root resolution failed: %s", exc)
        return {"error": str(exc), "status": "validation_failed"}

    shared = Path(local_shared_root)
    results_dir = shared / "results"

    # Pull latest status from GitHub before searching
    _git_pull(shared)

    # Search queue directories first
    queue_status = _find_in_queue(shared, inp.job_id)
    if queue_status:
        _notify(f"[{_ts()}] ⏳ STATUS — Job: {inp.job_id} | Status: {queue_status.upper()} (in queue)")
        return GetExecutionStatusOutput(
            job_id=inp.job_id, status=queue_status
        ).model_dump()

    # Search result folders
    result_folder = _find_result_folder(results_dir, inp.job_id)
    if result_folder is None:
        _notify(f"[{_ts()}] ⚠️  STATUS — Job: {inp.job_id} | Not found in any folder")
        return GetExecutionStatusOutput(
            job_id=inp.job_id, status="not_found"
        ).model_dump()

    meta_data = _read_json_file(result_folder / "metadata.json")
    summary_data = _read_json_file(result_folder / "summary.json")
    live_log_path = result_folder / "runner_live.log"

    status = meta_data.get("status", "unknown") if meta_data else "unknown"
    test_name = meta_data.get("test_name", "") if meta_data else ""
    started_at = meta_data.get("started_at", "") if meta_data else ""
    completed_at = meta_data.get("completed_at") if meta_data else None

    metrics = _kpi_from_summary(summary_data) if summary_data else None

    # Read last line of live log
    last_log_line: str | None = None
    live_log_available = live_log_path.exists()
    if live_log_available:
        try:
            lines = live_log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            last_log_line = lines[-1] if lines else None
        except OSError:
            live_log_available = False

    _notify(
        f"[{_ts()}] 📋 STATUS — Job: {inp.job_id} | Status: {status.upper()} | "
        f"Test: {test_name} | Started: {started_at}"
    )

    output = GetExecutionStatusOutput(
        job_id=inp.job_id,
        status=status,
        test_name=test_name,
        started_at=started_at,
        completed_at=completed_at,
        metrics=metrics,
        result_folder=str(result_folder),
        live_log_available=live_log_available,
        last_vm_log_line=last_log_line,
    )
    return output.model_dump()


# ---------------------------------------------------------------------------
# Tool 3: generate_daily_report
# ---------------------------------------------------------------------------


@mcp.tool()
def generate_daily_report(
    shared_root: str,
    date: str,
    test_name: str | None = None,
    notification_channel: str = "terminal",
) -> dict[str, Any]:
    """Scan results folder, parse all rounds for the date, and generate HTML report.

    Discovers round folders by artifact-based detection (*.jtl + metadata.json),
    parses each JTL file, builds comparison tables and observations, generates
    a stakeholder HTML report, and sends notifications.

    Args:
        shared_root: UNC path or VM-local drive path to the shared folder.
        date: Date to report on in YYYY-MM-DD format.
        test_name: Optional filter to a specific test name. None for all tests.
        notification_channel: One of ``terminal`` | ``teams`` | ``slack`` | ``both``.

    Returns:
        Dict matching :class:`GenerateDailyReportOutput` schema.

    Example:
        >>> report = generate_daily_report(
        ...     shared_root="L:\\\\Testlogfiles\\\\MCP_Testlogfiles_entry",
        ...     date="2026-04-29",
        ...     test_name=None,
        ...     notification_channel="terminal",
        ... )
    """
    _notify_client_connected_once()

    try:
        inp = GenerateDailyReportInput(
            shared_root=shared_root,
            date=date,
            test_name=test_name,
            notification_channel=notification_channel,
        )
    except Exception as exc:
        logger.error("generate_daily_report input validation failed: %s", exc)
        return {"error": str(exc), "status": "validation_failed"}

    try:
        local_shared_root = _resolve_local_shared_root(inp.shared_root)
    except ValueError as exc:
        logger.error("Shared root resolution failed: %s", exc)
        return {"error": str(exc), "status": "validation_failed"}

    shared = Path(local_shared_root)
    results_dir = shared / "results"

    # Pull latest results from GitHub before scanning
    _git_pull(shared)

    # Discover round folders
    round_folders = _discover_round_folders(results_dir, inp.date, inp.test_name)
    rounds_found = len(round_folders)

    _notify(
        f"[{_ts()}] 📊 REPORTING STARTED — "
        f"Scanning {inp.date} | Rounds found: {rounds_found}"
    )

    if rounds_found == 0:
        logger.warning("No result folders found for date %s in %s", inp.date, results_dir)
        return GenerateDailyReportOutput(
            date=inp.date,
            rounds_found=0,
            rounds_compared=0,
            html_report_path="",
            notification_status={},
            summary={"message": "No rounds found for this date"},
        ).model_dump()

    # Parse each round
    round_summaries: list[RoundSummary] = []
    parsed_results = []
    parse_errors: list[str] = []

    for idx, folder in enumerate(round_folders, start=1):
        try:
            jtl_path = find_jtl_file(folder)
            parsed = parse_jtl(jtl_path)
            meta_data = _read_json_file(folder / "metadata.json")
            test_name_meta = meta_data.get("test_name", folder.name) if meta_data else folder.name

            # Build KpiMetrics from TOTAL row
            total = parsed.total
            kpi = KpiMetrics(
                total_requests=total.sample_count,
                successful_requests=total.sample_count - total.error_count,
                failed_requests=total.error_count,
                error_rate_pct=total.error_pct,
                avg_response_ms=total.avg_ms,
                median_ms=total.median_ms,
                p90_ms=total.p90_ms,
                p95_ms=total.p95_ms,
                p99_ms=total.p99_ms,
                min_ms=total.min_ms,
                max_ms=total.max_ms,
                throughput_req_sec=total.throughput_req_sec,
                received_kb_sec=total.received_kb_sec,
                sent_kb_sec=total.sent_kb_sec,
            )

            summary = RoundSummary(
                round_number=idx,
                day_folder=folder.name,
                test_name=test_name_meta,
                metrics=kpi,
            )
            round_summaries.append(summary)
            parsed_results.append(parsed)

            _notify(
                f"[{_ts()}] 📋 PARSED Round {idx} — "
                f"{total.sample_count:,} requests | "
                f"Avg: {total.avg_ms:.0f}ms | "
                f"P95: {total.p95_ms:.0f}ms"
            )

        except (FileNotFoundError, ValueError) as exc:
            logger.error("Skipping round folder '%s': %s", folder, exc)
            parse_errors.append(f"Round {idx} ({folder.name}): {exc}")
            _notify(f"[{_ts()}] ⚠️  PARSE SKIPPED — Round {idx} | Folder: {folder.name} | Error: {exc}")

    if not round_summaries:
        return GenerateDailyReportOutput(
            date=inp.date,
            rounds_found=rounds_found,
            rounds_compared=0,
            html_report_path="",
            notification_status={},
            summary={"error": "All rounds failed to parse", "details": parse_errors},
        ).model_dump()

    # Generate HTML report
    report_filename = f"DAILY_REPORT_{inp.date}.html"
    report_path = results_dir / report_filename

    try:
        html_path = generate_html_report(
            rounds=round_summaries,
            parsed_results=parsed_results,
            date=inp.date,
            output_path=report_path,
        )
    except (ValueError, OSError) as exc:
        logger.error("HTML report generation failed: %s", exc, exc_info=True)
        return GenerateDailyReportOutput(
            date=inp.date,
            rounds_found=rounds_found,
            rounds_compared=len(round_summaries) - 1,
            html_report_path="",
            notification_status={},
            summary={"error": f"Report generation failed: {exc}"},
        ).model_dump()

    _notify(f"[{_ts()}] ✅ REPORT GENERATED — Path: {html_path}")

    # Send notifications
    best = min(round_summaries, key=lambda r: r.metrics.avg_response_ms)
    first_avg = round_summaries[0].metrics.avg_response_ms
    last_avg = round_summaries[-1].metrics.avg_response_ms
    delta_pct = ((last_avg - first_avg) / max(first_avg, 1)) * 100
    avg_error = sum(r.metrics.error_rate_pct for r in round_summaries) / len(round_summaries)

    if abs(delta_pct) < 5:
        trend = "stable"
    elif delta_pct > 0:
        trend = f"+{delta_pct:.1f}% degraded"
    else:
        trend = f"{delta_pct:.1f}% improved"

    notification_results = send_report_notification(
        notification_channel=inp.notification_channel,
        date=inp.date,
        rounds_found=len(round_summaries),
        best_round=f"Round {best.round_number}",
        avg_response_trend=trend,
        error_rate=avg_error,
        report_path=html_path,
    )

    notification_status_dict = {
        ch: status.model_dump()
        for ch, status in notification_results.items()
    }

    summary_dict = {
        "best_round": best.round_number,
        "best_avg_ms": best.metrics.avg_response_ms,
        "worst_round": max(round_summaries, key=lambda r: r.metrics.avg_response_ms).round_number,
        "avg_response_trend": trend,
        "avg_error_rate_pct": round(avg_error, 2),
        "parse_errors": parse_errors,
    }

    output = GenerateDailyReportOutput(
        date=inp.date,
        rounds_found=rounds_found,
        rounds_compared=max(len(round_summaries) - 1, 0),
        html_report_path=html_path,
        notification_status=notification_status_dict,
        summary=summary_dict,
    )
    return output.model_dump()


# ---------------------------------------------------------------------------
# Internal: auto-trigger report after job completion
# ---------------------------------------------------------------------------


def _auto_generate_report(shared_root: str, date: str, notification_channel: str) -> None:
    """Invoke generate_daily_report automatically after test completion (FR-002-6).

    Swallows all exceptions — report failure must not affect completion reporting.

    Args:
        shared_root: UNC path to shared folder.
        date: Date string for the completed test.
        notification_channel: Notification channel to use for report delivery.
    """
    try:
        generate_daily_report(
            shared_root=shared_root,
            date=date,
            test_name=None,
            notification_channel=notification_channel,
        )
    except Exception as exc:
        logger.error("Auto report generation failed (non-blocking): %s", exc, exc_info=True)
        _notify(f"[{_ts()}] ⚠️  AUTO REPORT FAILED — Error: {exc} | Report can be re-run manually.")


# ---------------------------------------------------------------------------
# Internal: queue / folder scan helpers
# ---------------------------------------------------------------------------


def _find_in_queue(shared: Path, job_id: str) -> str | None:
    """Check if job_id is present in any queue folder (__QUEUE__, __RUNNING__).

    Args:
        shared: Root shared path.
        job_id: Job identifier to search for.

    Returns:
        Status string if found in a queue folder, else None.
    """
    queue_map = {
        os.getenv("JOB_QUEUE_DIR", "__QUEUE__"): "queued",
        os.getenv("JOB_RUNNING_DIR", "__RUNNING__"): "running",
    }
    for folder_name, status in queue_map.items():
        job_file = shared / folder_name / f"{job_id}.json"
        if job_file.exists():
            return status
    return None


def _find_result_folder(results_dir: Path, job_id: str) -> Path | None:
    """Search result folders for one whose metadata.json contains the given job_id.

    Args:
        results_dir: results/ directory path.
        job_id: Job identifier to find.

    Returns:
        Path to the matching result folder, or None if not found.
    """
    if not results_dir.exists():
        return None
    try:
        entries = list(results_dir.iterdir())
    except OSError as exc:
        logger.warning("Cannot read results directory '%s': %s", results_dir, exc)
        return None
    for folder in entries:
        if not folder.is_dir():
            continue
        meta = _read_json_file(folder / "metadata.json")
        if meta and meta.get("job_id") == job_id:
            return folder
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _heartbeat_loop() -> None:
    """Emit a heartbeat to stderr every 30 seconds so the terminal shows the server is alive."""
    count = 0
    while True:
        time.sleep(30)
        count += 1
        _notify(f"[{_ts()}] ⏳ MCP HEARTBEAT — Server alive | Uptime: {count * 30}s | Waiting for tool calls")


def main() -> None:
    """Start the FastMCP server via stdio transport."""
    _notify(f"[{_ts()}] 🚀 MCP SERVER STARTED — perf-mcp ready | Tools: start_test_execution, get_execution_status, generate_daily_report")
    _notify(f"[{_ts()}] ⏳ MCP WAITING — Listening for VS Code Copilot tool calls via stdio")
    t = threading.Thread(target=_heartbeat_loop, daemon=True)
    t.start()
    mcp.run()


if __name__ == "__main__":
    main()
