"""
Tests for report_generator.py.

Coverage targets:
  - Happy path: single round, two rounds comparison, three rounds (first-vs-last)
  - Unhappy: no rounds, mismatched lengths, timeout exceeded, write failure
  - Observations and recommendation text verification
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from perf_mcp.models import KpiMetrics, RoundSummary
from perf_mcp.report_generator import (
    _build_observations,
    _build_recommendation,
    _build_comparison,
    generate_html_report,
    _REPORT_TIMEOUT_SECONDS,
)
from perf_mcp.jtl_parser import ParsedJtlResult
from perf_mcp.models import LabelStats


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_kpi(
    total: int = 10000,
    avg: float = 420.0,
    p90: float = 800.0,
    p95: float = 950.0,
    p99: float = 1200.0,
    min_ms: float = 50.0,
    max_ms: float = 3500.0,
    error_pct: float = 0.0,
    throughput: float = 200.0,
) -> KpiMetrics:
    errors = int(total * error_pct / 100)
    return KpiMetrics(
        total_requests=total,
        successful_requests=total - errors,
        failed_requests=errors,
        error_rate_pct=error_pct,
        avg_response_ms=avg,
        median_ms=avg * 0.9,
        p90_ms=p90,
        p95_ms=p95,
        p99_ms=p99,
        min_ms=min_ms,
        max_ms=max_ms,
        throughput_req_sec=throughput,
        received_kb_sec=50.0,
        sent_kb_sec=10.0,
    )


def _make_round(n: int, avg: float = 420.0, error_pct: float = 0.0) -> RoundSummary:
    return RoundSummary(
        round_number=n,
        day_folder=f"2026-04-29_Round{n}_14-30-00",
        test_name="GET_RO_Number",
        metrics=_make_kpi(avg=avg, error_pct=error_pct),
    )


def _make_label_stats(label: str = "TOTAL") -> LabelStats:
    return LabelStats(
        label=label,
        sample_count=10000,
        avg_ms=420.0,
        median_ms=380.0,
        p90_ms=800.0,
        p95_ms=950.0,
        p99_ms=1200.0,
        min_ms=50.0,
        max_ms=3500.0,
        error_count=0,
        error_pct=0.0,
        throughput_req_sec=200.0,
        received_kb_sec=50.0,
        sent_kb_sec=10.0,
    )


def _make_parsed(label: str = "GET /api") -> ParsedJtlResult:
    label_row = _make_label_stats(label)
    total_row = _make_label_stats("TOTAL")
    return ParsedJtlResult(
        jtl_path="C:\\dummy.jtl",
        label_rows=[label_row],
        total=total_row,
        test_duration_seconds=50.0,
        rows_parsed=10000,
        rows_skipped=0,
    )


# ---------------------------------------------------------------------------
# Happy path tests
# ---------------------------------------------------------------------------

class TestReportGeneratorHappyPath:
    def test_single_round_html_generated(self, tmp_path):
        rounds = [_make_round(1)]
        parsed = [_make_parsed()]
        out_path = tmp_path / "DAILY_REPORT_2026-04-29.html"
        result_path = generate_html_report(rounds, parsed, "2026-04-29", out_path)
        assert Path(result_path).exists()

    def test_html_contains_all_4_section_headings(self, tmp_path):
        rounds = [_make_round(1), _make_round(2, avg=450.0)]
        parsed = [_make_parsed(), _make_parsed()]
        out = tmp_path / "report.html"
        generate_html_report(rounds, parsed, "2026-04-29", out)
        html = out.read_text(encoding="utf-8")
        assert "Section 1" in html
        assert "Section 2" in html
        assert "Section 3" in html
        assert "Section 4" in html

    def test_html_contains_total_row(self, tmp_path):
        rounds = [_make_round(1)]
        parsed = [_make_parsed()]
        out = tmp_path / "report.html"
        generate_html_report(rounds, parsed, "2026-04-29", out)
        html = out.read_text(encoding="utf-8")
        assert "TOTAL" in html

    def test_comparison_table_has_correct_columns(self):
        rounds = [_make_round(1), _make_round(2)]
        rows = _build_comparison(rounds)
        metrics = [r["metric"] for r in rows]
        assert "Avg Response Time" in metrics
        assert "95th Percentile" in metrics
        assert "Error Rate" in metrics
        assert "Throughput" in metrics
        assert "Round 1" in rows[0]
        assert "Round 2" in rows[0]

    def test_observations_minimum_4_bullets(self):
        rounds = [_make_round(1), _make_round(2, avg=450.0)]
        obs = _build_observations(rounds)
        assert len(obs) >= 4

    def test_recommendation_mentions_best_round(self):
        rounds = [_make_round(1, avg=400.0), _make_round(2, avg=500.0)]
        rec = _build_recommendation(rounds)
        assert "Round 1" in rec

    def test_three_rounds_first_vs_last_summary(self, tmp_path):
        rounds = [_make_round(1, avg=400.0), _make_round(2, avg=420.0), _make_round(3, avg=480.0)]
        parsed = [_make_parsed() for _ in range(3)]
        out = tmp_path / "report.html"
        generate_html_report(rounds, parsed, "2026-04-29", out)
        html = out.read_text(encoding="utf-8")
        assert "Round 1" in html
        assert "Round 3" in html

    def test_high_error_rate_recommendation_says_do_not_proceed(self):
        rounds = [_make_round(1, error_pct=2.5)]
        rec = _build_recommendation(rounds)
        assert "DO NOT PROCEED" in rec

    def test_degradation_observation_included(self):
        # 25% degradation across rounds → root cause hypothesis should appear
        rounds = [_make_round(1, avg=400.0), _make_round(2, avg=500.0)]
        obs = _build_observations(rounds)
        combined = " ".join(obs)
        assert "Root cause" in combined or "degraded" in combined.lower()


# ---------------------------------------------------------------------------
# Unhappy path tests
# ---------------------------------------------------------------------------

class TestReportGeneratorUnhappyPath:
    def test_empty_rounds_raises(self, tmp_path):
        with pytest.raises(ValueError, match="no rounds"):
            generate_html_report([], [], "2026-04-29", tmp_path / "r.html")

    def test_mismatched_lengths_raises(self, tmp_path):
        with pytest.raises(ValueError, match="same length"):
            generate_html_report([_make_round(1)], [], "2026-04-29", tmp_path / "r.html")

    def test_timeout_raises(self, tmp_path):
        rounds = [_make_round(1)]
        parsed = [_make_parsed()]
        call_count = 0
        original_mono = time.monotonic
        def fake_monotonic():
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                return original_mono() + _REPORT_TIMEOUT_SECONDS + 5
            return original_mono()
        with patch("perf_mcp.report_generator.time.monotonic", side_effect=fake_monotonic):
            with pytest.raises(ValueError, match="timeout"):
                generate_html_report(rounds, parsed, "2026-04-29", tmp_path / "r.html")

    def test_write_failure_raises_os_error(self, tmp_path):
        rounds = [_make_round(1)]
        parsed = [_make_parsed()]
        # Point to a path that cannot be created (file as directory)
        bad_path = tmp_path / "not_a_dir.html" / "nested.html"
        # Create file where directory is expected
        (tmp_path / "not_a_dir.html").write_text("block", encoding="utf-8")
        with pytest.raises(OSError):
            generate_html_report(rounds, parsed, "2026-04-29", bad_path)

    def test_zero_error_rate_observation(self):
        rounds = [_make_round(1, error_pct=0.0)]
        obs = _build_observations(rounds)
        combined = " ".join(obs)
        assert "0.00%" in combined or "reliable" in combined.lower()

    def test_stable_recommendation_says_proceed(self):
        # Stable avg, zero errors → PROCEED
        rounds = [_make_round(1, avg=400.0), _make_round(2, avg=402.0)]
        rec = _build_recommendation(rounds)
        assert "PROCEED" in rec
