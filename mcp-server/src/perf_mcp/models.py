"""
Pydantic models for all MCP tool inputs, outputs, and internal data schemas.

All tool inputs and outputs are validated by these models before any logic
executes. This ensures type safety, input sanitisation, and clear API contracts.
"""

from __future__ import annotations

import re
from typing import Any
from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Shared / validation helpers
# ---------------------------------------------------------------------------

_TEST_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,100}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NOTIFICATION_CHANNELS = {"terminal", "teams", "slack", "both"}


# ---------------------------------------------------------------------------
# Tool 1: start_test_execution — Input / Output
# ---------------------------------------------------------------------------


class StartTestExecutionInput(BaseModel):
    """Input schema for start_test_execution MCP tool.

    Args:
        test_name: Logical name for the test run. Alphanumeric, underscores, and
            hyphens only (max 100 chars). Example: ``GET_RO_Number_Load``.
        script_path_on_vm: Absolute path to the JMeter .jmx script on the remote VM.
            Must match the ``ALLOWED_VM_SCRIPT_PREFIX`` environment variable prefix.
            Example: ``C:\\PerfTests\\Scripts\\GET_RO_Number.jmx``.
        shared_root: UNC path to the shared folder accessible by both machines.
            Example: ``\\\\vm-host\\PerfTest``.
        notification_channel: Destination for lifecycle notifications.
            One of ``terminal`` | ``teams`` | ``slack`` | ``both``.

    Example:
        >>> inp = StartTestExecutionInput(
        ...     test_name="GET_RO_Number_Load",
        ...     script_path_on_vm="C:\\\\PerfTests\\\\GET_RO_Number.jmx",
        ...     shared_root="\\\\\\\\vm-host\\\\PerfTest",
        ...     notification_channel="terminal",
        ... )
    """

    test_name: str = Field(..., description="Logical name for the test (alphanumeric, _ and - only, max 100 chars)")
    script_path_on_vm: str = Field(..., description="Absolute path to JMX script on VM")
    shared_root: str = Field(..., description="UNC path to the shared results folder")
    notification_channel: str = Field(default="terminal", description="terminal | teams | slack | both")

    @field_validator("test_name")
    @classmethod
    def validate_test_name(cls, v: str) -> str:
        """Reject names with characters that could enable path traversal."""
        if not _TEST_NAME_RE.match(v):
            raise ValueError(
                f"test_name '{v}' is invalid. Use alphanumeric characters, underscores, and hyphens only (max 100 chars)."
            )
        return v

    @field_validator("notification_channel")
    @classmethod
    def validate_channel(cls, v: str) -> str:
        """Ensure channel is one of the allowed values."""
        if v not in _NOTIFICATION_CHANNELS:
            raise ValueError(f"notification_channel must be one of {_NOTIFICATION_CHANNELS}, got '{v}'")
        return v

    @field_validator("shared_root")
    @classmethod
    def validate_unc_path(cls, v: str) -> str:
        """Basic UNC path format check — must start with \\\\ (two backslashes)."""
        if not v.startswith("\\\\") and not v.startswith("//"):
            raise ValueError(
                f"shared_root must be a UNC path starting with '\\\\\\\\'. Got: '{v}'"
            )
        return v


class StartTestExecutionOutput(BaseModel):
    """Output schema for start_test_execution MCP tool.

    Returns:
        job_id: Unique job identifier (HH-MM-SS_testName_XXXXXX).
        round: Round number for this test run on the given date (1-based).
        day_folder: Folder name created under results/ for this run.
        status: Current job status at time of return.
        result_folder: Full UNC path to the result folder.
        live_log_path: Full UNC path to runner_live.log for tailing.
        monitoring_mode: Whether live streaming or heartbeat-only monitoring was used.
    """

    job_id: str = Field(..., description="Unique job identifier HH-MM-SS_testName_XXXXXX")
    round: int = Field(..., description="Round number for today (1-based)")
    day_folder: str = Field(..., description="Folder name under results/")
    status: str = Field(..., description="queued | running | completed | failed")
    result_folder: str = Field(..., description="Full UNC path to result folder")
    live_log_path: str = Field(..., description="Full UNC path to runner_live.log")
    monitoring_mode: str = Field(..., description="live_stream | heartbeat_only")


# ---------------------------------------------------------------------------
# Tool 2: get_execution_status — Input / Output
# ---------------------------------------------------------------------------


class GetExecutionStatusInput(BaseModel):
    """Input schema for get_execution_status MCP tool.

    Args:
        job_id: Unique job identifier previously returned by start_test_execution.
        shared_root: UNC path to the shared folder (same value used at job creation).

    Example:
        >>> inp = GetExecutionStatusInput(
        ...     job_id="14-30-22_GET_RO_Number_abc123",
        ...     shared_root="\\\\\\\\vm-host\\\\PerfTest",
        ... )
    """

    job_id: str = Field(..., description="Job identifier returned by start_test_execution")
    shared_root: str = Field(..., description="UNC path to the shared results folder")

    @field_validator("shared_root")
    @classmethod
    def validate_unc_path(cls, v: str) -> str:
        """Basic UNC path format check."""
        if not v.startswith("\\\\") and not v.startswith("//"):
            raise ValueError(f"shared_root must be a UNC path starting with '\\\\\\\\'. Got: '{v}'")
        return v


class KpiMetrics(BaseModel):
    """Parsed KPI metrics from summary.json or JTL analysis.

    All response times are in milliseconds. All rates are computed values.
    """

    total_requests: int = Field(..., description="Total number of HTTP requests sampled")
    successful_requests: int = Field(..., description="Requests with success=true")
    failed_requests: int = Field(..., description="Requests with success=false")
    error_rate_pct: float = Field(..., description="(failed / total) * 100, two decimal places")
    avg_response_ms: float = Field(..., description="Mean elapsed time across all samples (ms)")
    median_ms: float = Field(..., description="50th percentile elapsed time (ms)")
    p90_ms: float = Field(..., description="90th percentile elapsed time (ms)")
    p95_ms: float = Field(..., description="95th percentile elapsed time (ms)")
    p99_ms: float = Field(..., description="99th percentile elapsed time (ms)")
    min_ms: float = Field(..., description="Minimum elapsed time (ms)")
    max_ms: float = Field(..., description="Maximum elapsed time (ms)")
    throughput_req_sec: float = Field(..., description="Total requests / test duration in seconds")
    received_kb_sec: float = Field(..., description="Bandwidth received (KB/s)")
    sent_kb_sec: float = Field(..., description="Bandwidth sent (KB/s)")


class GetExecutionStatusOutput(BaseModel):
    """Output schema for get_execution_status MCP tool.

    Returns:
        job_id: The queried job identifier.
        status: Current job status.
        test_name: Name of the test (from metadata.json).
        started_at: ISO-8601 timestamp when job execution started.
        completed_at: ISO-8601 timestamp when job completed, or None if still running.
        metrics: Full KPI breakdown if job is completed, else None.
        result_folder: Full path to the result folder.
        live_log_available: Whether runner_live.log exists and is readable.
        last_vm_log_line: Most recent line from runner_live.log, or None.
    """

    job_id: str = Field(..., description="The queried job identifier")
    status: str = Field(..., description="queued | running | completed | failed | timed_out | not_found")
    test_name: str = Field(default="", description="Test name from metadata.json")
    started_at: str = Field(default="", description="ISO-8601 start timestamp")
    completed_at: str | None = Field(default=None, description="ISO-8601 completion timestamp, None if running")
    metrics: KpiMetrics | None = Field(default=None, description="Full KPI metrics if completed, else None")
    result_folder: str = Field(default="", description="Full path to result folder")
    live_log_available: bool = Field(default=False, description="Whether runner_live.log is readable")
    last_vm_log_line: str | None = Field(default=None, description="Last line from runner_live.log")


# ---------------------------------------------------------------------------
# Tool 3: generate_daily_report — Input / Output
# ---------------------------------------------------------------------------


class GenerateDailyReportInput(BaseModel):
    """Input schema for generate_daily_report MCP tool.

    Args:
        shared_root: UNC path to the shared folder.
        date: Date to report on in YYYY-MM-DD format.
        test_name: Optional filter to a specific test name. Pass None for all tests.
        notification_channel: Destination for report delivery notification.

    Example:
        >>> inp = GenerateDailyReportInput(
        ...     shared_root="\\\\\\\\vm-host\\\\PerfTest",
        ...     date="2026-04-29",
        ...     test_name=None,
        ...     notification_channel="terminal",
        ... )
    """

    shared_root: str = Field(..., description="UNC path to the shared results folder")
    date: str = Field(..., description="Reporting date in YYYY-MM-DD format")
    test_name: str | None = Field(default=None, description="Filter to specific test, or None for all")
    notification_channel: str = Field(default="terminal", description="terminal | teams | slack | both")

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        """Enforce YYYY-MM-DD format to prevent path injection."""
        if not _DATE_RE.match(v):
            raise ValueError(f"date must be in YYYY-MM-DD format. Got: '{v}'")
        return v

    @field_validator("notification_channel")
    @classmethod
    def validate_channel(cls, v: str) -> str:
        """Ensure channel is one of the allowed values."""
        if v not in _NOTIFICATION_CHANNELS:
            raise ValueError(f"notification_channel must be one of {_NOTIFICATION_CHANNELS}, got '{v}'")
        return v

    @field_validator("shared_root")
    @classmethod
    def validate_unc_path(cls, v: str) -> str:
        """Basic UNC path format check."""
        if not v.startswith("\\\\") and not v.startswith("//"):
            raise ValueError(f"shared_root must be a UNC path starting with '\\\\\\\\'. Got: '{v}'")
        return v

    @field_validator("test_name")
    @classmethod
    def validate_test_name(cls, v: str | None) -> str | None:
        """If provided, test_name must pass same rules as in StartTestExecutionInput."""
        if v is not None and not _TEST_NAME_RE.match(v):
            raise ValueError(
                f"test_name '{v}' is invalid. Use alphanumeric characters, underscores, and hyphens only."
            )
        return v


class RoundSummary(BaseModel):
    """KPI summary for a single round, used in comparison tables.

    Args:
        round_number: Sequential round number (1-based) for that date.
        day_folder: Folder name under results/.
        test_name: Test name extracted from metadata.json.
        metrics: Parsed aggregate KPIs for the TOTAL row.
    """

    round_number: int = Field(..., description="Sequential round number (1-based)")
    day_folder: str = Field(..., description="Folder name under results/")
    test_name: str = Field(..., description="Test name from metadata.json")
    metrics: KpiMetrics = Field(..., description="Aggregate TOTAL KPIs for this round")


class NotificationStatus(BaseModel):
    """Delivery result for a single notification channel.

    Args:
        channel: Channel name (teams | slack | terminal).
        delivered: True if notification was successfully delivered.
        attempts: Number of attempts made (including retries).
        error: Error description if delivery failed, else None.
    """

    channel: str = Field(..., description="teams | slack | terminal")
    delivered: bool = Field(..., description="True if successfully delivered")
    attempts: int = Field(default=1, description="Total attempts including retries")
    error: str | None = Field(default=None, description="Error details if delivery failed")


class GenerateDailyReportOutput(BaseModel):
    """Output schema for generate_daily_report MCP tool.

    Returns:
        date: The reporting date.
        rounds_found: Total rounds discovered for the date.
        rounds_compared: Number of consecutive comparisons performed.
        html_report_path: Full UNC path to the generated HTML report.
        notification_status: Delivery status per channel.
        summary: High-level summary dict (best round, worst round, trend).
    """

    date: str = Field(..., description="Reporting date YYYY-MM-DD")
    rounds_found: int = Field(..., description="Total rounds discovered")
    rounds_compared: int = Field(..., description="Consecutive comparisons performed")
    html_report_path: str = Field(..., description="Full UNC path to generated HTML report")
    notification_status: dict[str, Any] = Field(default_factory=dict, description="Delivery status per channel")
    summary: dict[str, Any] = Field(default_factory=dict, description="High-level summary: best/worst round, trend")


# ---------------------------------------------------------------------------
# Internal: Job JSON schema (written to __QUEUE__)
# ---------------------------------------------------------------------------


class JobQueueEntry(BaseModel):
    """Schema for job JSON files written to __QUEUE__ folder.

    This is never exposed to MCP clients — used internally for type-safe
    file serialisation when creating job files on the UNC share.
    """

    job_id: str = Field(..., description="Unique job identifier")
    test_name: str = Field(..., description="Logical test name")
    script_path_on_vm: str = Field(..., description="Absolute JMX path on VM")
    round: int = Field(..., description="Round number for the day (1-based)")
    day_folder: str = Field(..., description="Result folder name under results/")
    created_at: str = Field(..., description="ISO-8601 creation timestamp")
    notification_channel: str = Field(..., description="terminal | teams | slack | both")
    status: str = Field(default="queued", description="Initial status — always 'queued'")


# ---------------------------------------------------------------------------
# Internal: Metadata JSON schema (written by VM runner to result folder)
# ---------------------------------------------------------------------------


class RunMetadata(BaseModel):
    """Schema for metadata.json files written by VM runner to each result folder.

    MCP reads this file to track execution status and detect completion/failure.
    """

    job_id: str = Field(..., description="Job identifier matching the queue entry")
    test_name: str = Field(..., description="Logical test name")
    script_path_on_vm: str = Field(..., description="JMX path that was executed")
    round: int = Field(..., description="Round number")
    day_folder: str = Field(..., description="Result folder name")
    status: str = Field(..., description="queued | running | completed | failed | timed_out")
    started_at: str = Field(default="", description="ISO-8601 timestamp when JMeter started")
    completed_at: str | None = Field(default=None, description="ISO-8601 completion timestamp")
    error_message: str | None = Field(default=None, description="Error details if status=failed")


# ---------------------------------------------------------------------------
# Internal: Heartbeat JSON schema (written by VM runner every 60 seconds)
# ---------------------------------------------------------------------------


class HeartbeatEntry(BaseModel):
    """Schema for heartbeat.json written by VM runner every 60 seconds.

    MCP reads this to confirm the runner is still alive during long tests.
    """

    job_id: str = Field(..., description="Active job identifier")
    timestamp: str = Field(..., description="ISO-8601 heartbeat timestamp")
    elapsed_seconds: int = Field(..., description="Seconds since test started")
    jmeter_running: bool = Field(..., description="True if JMeter process is active")


# ---------------------------------------------------------------------------
# Internal: Per-label parsed row (used by jtl_parser internally)
# ---------------------------------------------------------------------------


class LabelStats(BaseModel):
    """Parsed statistics for a single transaction label from a JTL file.

    Computed from raw ``elapsed`` column values — NOT from JMeter's summary row.
    """

    label: str = Field(..., description="Transaction label from JTL 'label' column")
    sample_count: int = Field(..., description="Total number of samples for this label")
    avg_ms: float = Field(..., description="Mean elapsed time (ms)")
    median_ms: float = Field(..., description="50th percentile elapsed time (ms)")
    p90_ms: float = Field(..., description="90th percentile elapsed time (ms)")
    p95_ms: float = Field(..., description="95th percentile elapsed time (ms)")
    p99_ms: float = Field(..., description="99th percentile elapsed time (ms)")
    min_ms: float = Field(..., description="Minimum elapsed time (ms)")
    max_ms: float = Field(..., description="Maximum elapsed time (ms)")
    error_count: int = Field(..., description="Rows where success='false'")
    error_pct: float = Field(..., description="(error_count / sample_count) * 100")
    throughput_req_sec: float = Field(..., description="Requests per second for this label")
    received_kb_sec: float = Field(..., description="Received bandwidth (KB/s)")
    sent_kb_sec: float = Field(..., description="Sent bandwidth (KB/s)")


class ParsedJtlResult(BaseModel):
    """Full result of parsing one JTL file — per-label rows plus a TOTAL aggregate row.

    Args:
        jtl_path: Absolute path to the source JTL file.
        label_rows: One LabelStats per distinct transaction label.
        total: Aggregate TOTAL row across all labels.
        test_duration_seconds: Derived from max(timeStamp) - min(timeStamp), in seconds.
        rows_parsed: Total data rows successfully parsed.
        rows_skipped: Rows skipped due to malformed data.
    """

    jtl_path: str = Field(..., description="Source JTL file path")
    label_rows: list[LabelStats] = Field(..., description="Per-label parsed statistics")
    total: LabelStats = Field(..., description="TOTAL aggregate across all labels")
    test_duration_seconds: float = Field(..., description="Test duration from first to last timestamp (seconds)")
    rows_parsed: int = Field(..., description="Total data rows successfully parsed")
    rows_skipped: int = Field(default=0, description="Rows skipped due to malformed data")
