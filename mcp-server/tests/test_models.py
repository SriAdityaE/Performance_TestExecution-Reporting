"""
Tests for Pydantic models validation.

Coverage targets:
  - Happy path: valid inputs pass validation for all 3 tool inputs
  - Unhappy: invalid test_name, invalid date format, invalid channel,
             invalid UNC path, missing required fields, script prefix violation
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from perf_mcp.models import (
    GenerateDailyReportInput,
    GetExecutionStatusInput,
    JobQueueEntry,
    KpiMetrics,
    StartTestExecutionInput,
)


class TestStartTestExecutionInputValidation:
    def test_valid_input_passes(self):
        inp = StartTestExecutionInput(
            test_name="GET_RO_Number_Load",
            script_path_on_vm="C:\\PerfTests\\test.jmx",
            shared_root="\\\\vm-host\\PerfTest",
            notification_channel="terminal",
        )
        assert inp.test_name == "GET_RO_Number_Load"

    def test_all_valid_channels_pass(self):
        for ch in ("terminal", "teams", "slack", "both"):
            inp = StartTestExecutionInput(
                test_name="Test1",
                script_path_on_vm="C:\\PerfTests\\test.jmx",
                shared_root="\\\\vm\\share",
                notification_channel=ch,
            )
            assert inp.notification_channel == ch

    def test_invalid_test_name_special_chars(self):
        with pytest.raises(ValidationError, match="invalid"):
            StartTestExecutionInput(
                test_name="test/../etc/passwd",
                script_path_on_vm="C:\\test.jmx",
                shared_root="\\\\vm\\share",
            )

    def test_invalid_test_name_too_long(self):
        with pytest.raises(ValidationError):
            StartTestExecutionInput(
                test_name="a" * 101,
                script_path_on_vm="C:\\test.jmx",
                shared_root="\\\\vm\\share",
            )

    def test_invalid_channel_raises(self):
        with pytest.raises(ValidationError, match="notification_channel"):
            StartTestExecutionInput(
                test_name="Test1",
                script_path_on_vm="C:\\test.jmx",
                shared_root="\\\\vm\\share",
                notification_channel="email",
            )

    def test_invalid_unc_path_raises(self):
        with pytest.raises(ValidationError, match="UNC"):
            StartTestExecutionInput(
                test_name="Test1",
                script_path_on_vm="C:\\test.jmx",
                shared_root="C:\\local\\path",
            )

    def test_empty_test_name_raises(self):
        with pytest.raises(ValidationError):
            StartTestExecutionInput(
                test_name="",
                script_path_on_vm="C:\\test.jmx",
                shared_root="\\\\vm\\share",
            )

    def test_missing_required_fields_raises(self):
        with pytest.raises(ValidationError):
            StartTestExecutionInput(test_name="Test1")  # missing script_path_on_vm and shared_root


class TestGetExecutionStatusInputValidation:
    def test_valid_input_passes(self):
        inp = GetExecutionStatusInput(
            job_id="14-30-22_Test_abc123",
            shared_root="\\\\vm\\share",
        )
        assert inp.job_id == "14-30-22_Test_abc123"

    def test_invalid_unc_raises(self):
        with pytest.raises(ValidationError, match="UNC"):
            GetExecutionStatusInput(job_id="abc123", shared_root="C:\\local")

    def test_missing_job_id_raises(self):
        with pytest.raises(ValidationError):
            GetExecutionStatusInput(shared_root="\\\\vm\\share")


class TestGenerateDailyReportInputValidation:
    def test_valid_input_passes(self):
        inp = GenerateDailyReportInput(
            shared_root="\\\\vm\\share",
            date="2026-04-29",
            notification_channel="teams",
        )
        assert inp.date == "2026-04-29"

    def test_invalid_date_format_raises(self):
        with pytest.raises(ValidationError, match="YYYY-MM-DD"):
            GenerateDailyReportInput(
                shared_root="\\\\vm\\share",
                date="29-04-2026",
            )

    def test_date_with_slash_raises(self):
        with pytest.raises(ValidationError):
            GenerateDailyReportInput(
                shared_root="\\\\vm\\share",
                date="2026/04/29",
            )

    def test_invalid_test_name_filter_raises(self):
        with pytest.raises(ValidationError):
            GenerateDailyReportInput(
                shared_root="\\\\vm\\share",
                date="2026-04-29",
                test_name="test/../hack",
            )

    def test_none_test_name_allowed(self):
        inp = GenerateDailyReportInput(
            shared_root="\\\\vm\\share",
            date="2026-04-29",
            test_name=None,
        )
        assert inp.test_name is None

    def test_invalid_channel_raises(self):
        with pytest.raises(ValidationError):
            GenerateDailyReportInput(
                shared_root="\\\\vm\\share",
                date="2026-04-29",
                notification_channel="sms",
            )


class TestKpiMetricsModel:
    def test_valid_kpi_passes(self):
        kpi = KpiMetrics(
            total_requests=1000,
            successful_requests=990,
            failed_requests=10,
            error_rate_pct=1.0,
            avg_response_ms=420.0,
            median_ms=400.0,
            p90_ms=800.0,
            p95_ms=950.0,
            p99_ms=1200.0,
            min_ms=50.0,
            max_ms=3500.0,
            throughput_req_sec=200.0,
            received_kb_sec=50.0,
            sent_kb_sec=10.0,
        )
        assert kpi.total_requests == 1000

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            KpiMetrics(total_requests=1000)  # missing many required fields
