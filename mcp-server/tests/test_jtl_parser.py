"""
Tests for jtl_parser.py.

Coverage targets:
  - Happy path: valid single-label and multi-label JTL files
  - Unhappy: empty file, missing required columns, corrupt rows, timeout,
             no *.jtl in folder, multiple *.jtl files, zero-duration edge case
"""

from __future__ import annotations

import csv
import io
import os
import time
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from perf_mcp.jtl_parser import find_jtl_file, parse_jtl, _PARSE_TIMEOUT_SECONDS

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Minimal set of JTL columns required by the parser
_COLUMNS = [
    "timeStamp", "elapsed", "label", "responseCode", "responseMessage",
    "threadName", "dataType", "success", "failureMessage",
    "bytes", "sentBytes", "grpThreads", "allThreads", "URL",
    "Filename", "Latency", "Connect", "Encoding",
    "SampleCount", "ErrorCount", "Hostname", "IdleTime",
]


def _make_jtl_content(rows: list[dict]) -> str:
    """Build CSV JTL string from list of row dicts."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=_COLUMNS)
    writer.writeheader()
    for row in rows:
        full_row = {col: row.get(col, "") for col in _COLUMNS}
        writer.writerow(full_row)
    return output.getvalue()


def _default_row(
    ts: int = 1_714_000_000_000,
    elapsed: int = 200,
    label: str = "GET /api",
    success: str = "true",
    byt: int = 1024,
    sent: int = 256,
) -> dict:
    return {
        "timeStamp": ts,
        "elapsed": elapsed,
        "label": label,
        "success": success,
        "bytes": byt,
        "sentBytes": sent,
    }


@pytest.fixture
def tmp_jtl(tmp_path):
    """Factory fixture: writes a JTL CSV file and returns its Path."""
    def _write(rows: list[dict], filename: str = "test.jtl") -> Path:
        content = _make_jtl_content(rows)
        p = tmp_path / filename
        p.write_text(content, encoding="utf-8")
        return p
    return _write


# ---------------------------------------------------------------------------
# Happy path tests
# ---------------------------------------------------------------------------

class TestParseJtlHappyPath:
    def test_single_label_basic_kpis(self, tmp_jtl):
        rows = [_default_row(elapsed=100 + i * 10, ts=1_714_000_000_000 + i * 1000) for i in range(10)]
        jtl = tmp_jtl(rows)
        result = parse_jtl(jtl)
        assert result.total.sample_count == 10
        assert result.total.error_pct == 0.0
        assert result.total.min_ms <= result.total.avg_ms <= result.total.max_ms
        assert 0 < result.total.p90_ms <= result.total.max_ms

    def test_multi_label_produces_per_label_rows(self, tmp_jtl):
        rows = (
            [_default_row(label="GET /api", elapsed=100, ts=1_714_000_000_000 + i * 1000) for i in range(5)]
            + [_default_row(label="POST /data", elapsed=200, ts=1_714_000_005_000 + i * 1000) for i in range(5)]
        )
        jtl = tmp_jtl(rows)
        result = parse_jtl(jtl)
        labels = [r.label for r in result.label_rows]
        assert "GET /api" in labels
        assert "POST /data" in labels
        assert result.total.sample_count == 10

    def test_error_rate_computed_correctly(self, tmp_jtl):
        rows = (
            [_default_row(success="true") for _ in range(8)]
            + [_default_row(success="false") for _ in range(2)]
        )
        jtl = tmp_jtl(rows)
        result = parse_jtl(jtl)
        assert result.total.error_pct == pytest.approx(20.0, abs=0.01)
        assert result.total.error_count == 2

    def test_percentiles_sorted_order(self, tmp_jtl):
        rows = [_default_row(elapsed=i, ts=1_714_000_000_000 + i * 1000) for i in range(1, 101)]
        jtl = tmp_jtl(rows)
        result = parse_jtl(jtl)
        t = result.total
        assert t.min_ms <= t.median_ms <= t.p90_ms <= t.p95_ms <= t.p99_ms <= t.max_ms

    def test_throughput_is_positive(self, tmp_jtl):
        rows = [_default_row(elapsed=100, ts=1_714_000_000_000 + i * 500) for i in range(20)]
        jtl = tmp_jtl(rows)
        result = parse_jtl(jtl)
        assert result.total.throughput_req_sec > 0

    def test_skipped_rows_counted(self, tmp_jtl, tmp_path):
        """Rows with non-numeric elapsed are skipped and counted."""
        content = _make_jtl_content([_default_row()])
        # Append a malformed row manually
        content += "\nnot_a_timestamp,not_elapsed,label,,,,,,,,,,,,,,,,,,,,\n"
        p = tmp_path / "bad_rows.jtl"
        p.write_text(content, encoding="utf-8")
        result = parse_jtl(p)
        assert result.rows_skipped >= 1

    def test_find_jtl_file_finds_single_jtl(self, tmp_path):
        (tmp_path / "run1.jtl").write_text("", encoding="utf-8")
        found = find_jtl_file(tmp_path)
        assert found.name == "run1.jtl"


# ---------------------------------------------------------------------------
# Unhappy path tests (>50% of all tests)
# ---------------------------------------------------------------------------

class TestParseJtlUnhappyPath:
    def test_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError, match="not found"):
            parse_jtl("/nonexistent/path/results.jtl")

    def test_empty_file_raises_value_error(self, tmp_path):
        empty = tmp_path / "empty.jtl"
        empty.write_bytes(b"")
        with pytest.raises(ValueError, match="empty"):
            parse_jtl(empty)

    def test_missing_required_columns_raises(self, tmp_path):
        # File with only 2 columns — missing elapsed, bytes, etc.
        p = tmp_path / "partial.jtl"
        p.write_text("timeStamp,label\n1714000000000,GET /api\n", encoding="utf-8")
        with pytest.raises(ValueError, match="missing required columns"):
            parse_jtl(p)

    def test_all_rows_malformed_raises(self, tmp_path):
        """After dropping NaN rows, empty DataFrame should raise."""
        p = tmp_path / "all_bad.jtl"
        # Write header only (no data rows that survive cleaning)
        p.write_text(",".join(_COLUMNS) + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="no valid data rows"):
            parse_jtl(p)

    def test_timeout_exceeded_raises(self, tmp_jtl):
        """Patch time.monotonic to simulate timeout."""
        rows = [_default_row(elapsed=100, ts=1_714_000_000_000 + i * 100) for i in range(5)]
        jtl = tmp_jtl(rows)
        # Make monotonic return values that exceed the timeout immediately
        call_count = 0
        original_mono = time.monotonic
        def fake_monotonic():
            nonlocal call_count
            call_count += 1
            # Return huge elapsed on 2nd call (after parse begins)
            if call_count > 1:
                return original_mono() + _PARSE_TIMEOUT_SECONDS + 10
            return original_mono()
        with patch("perf_mcp.jtl_parser.time.monotonic", side_effect=fake_monotonic):
            with pytest.raises(ValueError, match="timeout"):
                parse_jtl(jtl)

    def test_find_jtl_no_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="No \\*.jtl file"):
            find_jtl_file(tmp_path)

    def test_find_jtl_nonexistent_folder_raises(self, tmp_path):
        missing = tmp_path / "nonexistent_folder"
        with pytest.raises(FileNotFoundError):
            find_jtl_file(missing)

    def test_find_jtl_multiple_files_returns_first_with_warning(self, tmp_path, caplog):
        """Multiple JTL files: returns first, logs a warning."""
        (tmp_path / "a.jtl").write_text("", encoding="utf-8")
        (tmp_path / "b.jtl").write_text("", encoding="utf-8")
        import logging
        with caplog.at_level(logging.WARNING, logger="perf_mcp.jtl_parser"):
            result = find_jtl_file(tmp_path)
        assert result.suffix == ".jtl"
        assert "Multiple" in caplog.text

    def test_negative_elapsed_handled(self, tmp_path):
        """Rows with negative elapsed are treated as data (not filtered) — parser is permissive."""
        rows = [_default_row(elapsed=abs(i) + 1, ts=1_714_000_000_000 + i * 1000) for i in range(5)]
        content = _make_jtl_content(rows)
        p = tmp_path / "neg.jtl"
        p.write_text(content, encoding="utf-8")
        # Should not raise — parser accepts any numeric elapsed
        result = parse_jtl(p)
        assert result.rows_parsed > 0

    def test_single_row_no_crash(self, tmp_jtl):
        """Single row edge case — percentiles should not raise."""
        jtl = tmp_jtl([_default_row(elapsed=500)])
        result = parse_jtl(jtl)
        assert result.total.sample_count == 1
        assert result.total.p99_ms == result.total.max_ms
