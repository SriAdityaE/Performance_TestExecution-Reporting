"""
HTML report generator for JMeter multi-round performance analysis.

Generates a stakeholder-grade HTML report with exactly 4 mandatory sections:
  1. Per-round JMeter results table (with TOTAL row)
  2. Consolidated comparison table (all rounds side by side)
  3. Key observations (architect-level, minimum 4 bullets)
  4. Recommendation paragraph

Design decisions:
- Uses Jinja2 for HTML templating to keep logic and markup cleanly separated.
- All analysis (trend, percentile, error rate, root cause) is deterministic.
- Report generation must complete within 60 seconds (NFR-001-2).
- No external network calls — purely local computation and file write.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, BaseLoader

from .models import LabelStats, ParsedJtlResult, RoundSummary

logger = logging.getLogger(__name__)

# Generation timeout per NFR-001-2
_REPORT_TIMEOUT_SECONDS = 60.0


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_html_report(
    rounds: list[RoundSummary],
    parsed_results: list[ParsedJtlResult],
    date: str,
    output_path: str | Path,
) -> str:
    """Generate a stakeholder HTML performance report and write it to disk.

    Produces all 4 mandatory sections: per-round tables, consolidated comparison,
    key observations, and recommendation. Raises if generation exceeds 60 seconds.

    Args:
        rounds: Ordered list of :class:`RoundSummary` objects (Round 1 first).
        parsed_results: Corresponding :class:`ParsedJtlResult` objects, same order as ``rounds``.
        date: Report date string (YYYY-MM-DD), used in titles and filename.
        output_path: Full path where the HTML file will be written.

    Returns:
        Absolute path string of the written HTML report file.

    Raises:
        ValueError: If generation exceeds 60-second timeout, or no rounds provided.
        OSError: If the output file cannot be written.

    Example:
        >>> path = generate_html_report(rounds, parsed, "2026-04-29", "\\\\\\\\vm\\\\PerfTest\\\\results\\\\DAILY_REPORT_2026-04-29.html")
    """
    if not rounds:
        raise ValueError("Cannot generate report: no rounds provided.")

    if len(rounds) != len(parsed_results):
        raise ValueError(
            f"rounds and parsed_results must have the same length. "
            f"Got {len(rounds)} rounds and {len(parsed_results)} parsed results."
        )

    start_time = time.monotonic()
    output_path = Path(output_path)

    # Section 3 & 4: analysis
    observations = _build_observations(rounds)
    recommendation = _build_recommendation(rounds)

    # Section 2: comparison data
    comparison = _build_comparison(rounds)

    _check_timeout(start_time)

    # Render HTML
    html = _render_html(
        date=date,
        rounds=rounds,
        parsed_results=parsed_results,
        comparison=comparison,
        observations=observations,
        recommendation=recommendation,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    _check_timeout(start_time)

    # Write file
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
    except OSError as exc:
        logger.error("Failed to write HTML report to '%s': %s", output_path, exc)
        raise

    elapsed = time.monotonic() - start_time
    logger.info("HTML report generated in %.2fs: %s", elapsed, output_path)
    return str(output_path)


# ---------------------------------------------------------------------------
# Analysis builders (Section 3 & 4)
# ---------------------------------------------------------------------------


def _build_observations(rounds: list[RoundSummary]) -> list[str]:
    """Build architect-level observations (minimum 4 bullets) from round data.

    Covers: trend, percentile analysis, max response time, error rate,
    throughput stability, and root cause hypothesis when applicable.

    Args:
        rounds: Ordered list of round summaries.

    Returns:
        List of observation strings (each is one bullet point).
    """
    obs: list[str] = []
    n = len(rounds)
    first = rounds[0].metrics
    last = rounds[-1].metrics

    # 1. Trend across rounds
    avg_delta_pct = ((last.avg_response_ms - first.avg_response_ms) / max(first.avg_response_ms, 1)) * 100
    if abs(avg_delta_pct) < 5:
        trend_label = "stable"
        trend_icon = "✅"
    elif avg_delta_pct > 0:
        trend_label = f"degraded by {avg_delta_pct:.1f}%"
        trend_icon = "⚠️"
    else:
        trend_label = f"improved by {abs(avg_delta_pct):.1f}%"
        trend_icon = "✅"

    obs.append(
        f"{trend_icon} Performance trend across {n} round(s) is **{trend_label}**. "
        f"Average response time moved from {first.avg_response_ms:.0f}ms (Round 1) "
        f"to {last.avg_response_ms:.0f}ms (Round {n})."
    )

    # 2. Percentile analysis (p95 and p99 — SLA-relevant)
    p95_delta = last.p95_ms - first.p95_ms
    p99_delta = last.p99_ms - first.p99_ms
    p95_icon = "⚠️" if p95_delta > 50 else "✅"
    p99_icon = "⚠️" if p99_delta > 100 else "✅"
    obs.append(
        f"{p95_icon} Percentile analysis: P95 shifted by {p95_delta:+.0f}ms "
        f"({first.p95_ms:.0f}ms → {last.p95_ms:.0f}ms). "
        f"{p99_icon} P99 shifted by {p99_delta:+.0f}ms "
        f"({first.p99_ms:.0f}ms → {last.p99_ms:.0f}ms). "
        "P95/P99 divergence from average indicates tail latency risk."
    )

    # 3. Max response time (tail latency)
    max_all = max(r.metrics.max_ms for r in rounds)
    max_round = next(r for r in rounds if r.metrics.max_ms == max_all)
    max_icon = "⚠️" if max_all > last.p99_ms * 3 else "ℹ️"
    obs.append(
        f"{max_icon} Max response time across all rounds: {max_all:.0f}ms "
        f"(observed in Round {max_round.round_number}). "
        f"This is {max_all / max(last.avg_response_ms, 1):.1f}x the average, "
        "suggesting occasional outlier spikes that may indicate GC pauses, thread contention, or network latency."
    )

    # 4. Error rate analysis
    max_error = max(r.metrics.error_rate_pct for r in rounds)
    error_icon = "❌" if max_error > 1.0 else ("⚠️" if max_error > 0.1 else "✅")
    if max_error == 0:
        obs.append("✅ Error rate: 0.00% across all rounds. System is highly reliable under the tested load.")
    else:
        worst_err_round = next(r for r in rounds if r.metrics.error_rate_pct == max_error)
        obs.append(
            f"{error_icon} Error rate reached {max_error:.2f}% in Round {worst_err_round.round_number}. "
            f"Error rates above 1% indicate application instability under load. "
            "Investigate server logs for 5xx responses and connection resets."
        )

    # 5. Throughput stability
    throughput_vals = [r.metrics.throughput_req_sec for r in rounds]
    tp_min = min(throughput_vals)
    tp_max = max(throughput_vals)
    tp_variance_pct = ((tp_max - tp_min) / max(tp_min, 0.001)) * 100
    tp_icon = "⚠️" if tp_variance_pct > 10 else "✅"
    obs.append(
        f"{tp_icon} Throughput stability: range {tp_min:.1f}–{tp_max:.1f} req/s "
        f"({tp_variance_pct:.1f}% variance). "
        + ("Throughput is consistent — server capacity is confirmed stable."
           if tp_variance_pct <= 10
           else "High variance in throughput suggests resource contention or variable think-time distribution.")
    )

    # 6. Root cause hypothesis if degradation detected
    if avg_delta_pct > 10:
        obs.append(
            "🔍 Root cause hypothesis: Progressive average degradation (>10%) across runs suggests "
            "server-side resource accumulation — likely candidates include JVM heap growth, "
            "database connection pool exhaustion, or cache warm-up effects. "
            "Recommend collecting GC logs and thread dumps during Round 3+ runs."
        )

    return obs


def _build_recommendation(rounds: list[RoundSummary]) -> str:
    """Build a single actionable recommendation paragraph.

    Args:
        rounds: Ordered list of round summaries.

    Returns:
        Recommendation paragraph as a string.
    """
    # Find best round by avg response time
    best = min(rounds, key=lambda r: r.metrics.avg_response_ms)
    worst = max(rounds, key=lambda r: r.metrics.avg_response_ms)
    max_error = max(r.metrics.error_rate_pct for r in rounds)
    last = rounds[-1].metrics
    first = rounds[0].metrics
    avg_delta_pct = ((last.avg_response_ms - first.avg_response_ms) / max(first.avg_response_ms, 1)) * 100

    if max_error > 1.0:
        verdict = "DO NOT PROCEED — error rate exceeds 1%"
        next_steps = (
            f"Investigate application logs for Round {worst.round_number} failures. "
            "Fix error-causing transactions before re-running load tests."
        )
    elif avg_delta_pct > 15:
        verdict = "INVESTIGATE before proceeding — performance is degrading"
        next_steps = (
            "Collect JVM heap dumps and GC logs from the application server. "
            "Check database slow query logs. Re-run with a 30-minute soak test to confirm stability."
        )
    else:
        verdict = "PROCEED — performance is acceptable"
        next_steps = (
            "Baseline is established. Schedule regression test before next deployment "
            "to detect any performance regressions early."
        )

    return (
        f"**Round {best.round_number}** delivered the best performance with an average response time of "
        f"{best.metrics.avg_response_ms:.0f}ms, P95 of {best.metrics.p95_ms:.0f}ms, and "
        f"error rate of {best.metrics.error_rate_pct:.2f}%. "
        f"Verdict: **{verdict}**. "
        f"{next_steps}"
    )


def _build_comparison(rounds: list[RoundSummary]) -> list[dict]:
    """Build the consolidated comparison data for Section 2.

    Args:
        rounds: Ordered list of round summaries.

    Returns:
        List of row dicts; each dict has 'metric' key and one key per round.
    """
    def _row(metric: str, values: list) -> dict:
        row = {"metric": metric}
        for i, v in enumerate(values):
            row[f"Round {rounds[i].round_number}"] = v
        return row

    def _ms(val: float) -> str:
        return f"{val:.0f} ms"

    def _pct(val: float) -> str:
        return f"{val:.2f}%"

    def _rps(val: float) -> str:
        return f"{val:.1f} req/s"

    rows = [
        _row("# Samples", [r.metrics.total_requests for r in rounds]),
        _row("Avg Response Time", [_ms(r.metrics.avg_response_ms) for r in rounds]),
        _row("Median", [_ms(r.metrics.median_ms) for r in rounds]),
        _row("90th Percentile", [_ms(r.metrics.p90_ms) for r in rounds]),
        _row("95th Percentile", [_ms(r.metrics.p95_ms) for r in rounds]),
        _row("99th Percentile", [_ms(r.metrics.p99_ms) for r in rounds]),
        _row("Min", [_ms(r.metrics.min_ms) for r in rounds]),
        _row("Max", [_ms(r.metrics.max_ms) for r in rounds]),
        _row("Error Rate", [_pct(r.metrics.error_rate_pct) for r in rounds]),
        _row("Throughput", [_rps(r.metrics.throughput_req_sec) for r in rounds]),
    ]
    return rows


def _check_timeout(start_time: float) -> None:
    """Raise ValueError if report generation has exceeded 60 seconds.

    Args:
        start_time: ``time.monotonic()`` recorded at generation start.

    Raises:
        ValueError: If elapsed time exceeds ``_REPORT_TIMEOUT_SECONDS``.
    """
    elapsed = time.monotonic() - start_time
    if elapsed > _REPORT_TIMEOUT_SECONDS:
        raise ValueError(
            f"Report generation timeout exceeded ({elapsed:.1f}s > {_REPORT_TIMEOUT_SECONDS}s). "
            "Too many rounds or JTL data is unexpectedly large."
        )


# ---------------------------------------------------------------------------
# Jinja2 HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>JMeter Performance Report — {{ date }}</title>
<style>
  body { font-family: 'Segoe UI', Arial, sans-serif; margin: 0; padding: 20px; background: #f5f7fa; color: #2d3748; }
  h1 { color: #1a365d; border-bottom: 3px solid #3182ce; padding-bottom: 10px; }
  h2 { color: #2b6cb0; margin-top: 40px; border-left: 4px solid #3182ce; padding-left: 12px; }
  h3 { color: #2c5282; margin-top: 28px; }
  table { border-collapse: collapse; width: 100%; margin: 16px 0; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-radius: 6px; overflow: hidden; }
  th { background: #2b6cb0; color: white; padding: 10px 14px; text-align: left; font-size: 13px; }
  td { padding: 9px 14px; border-bottom: 1px solid #e2e8f0; font-size: 13px; }
  tr:last-child td { border-bottom: none; }
  tr:nth-child(even) { background: #f7fafc; }
  tr.total-row td { font-weight: bold; background: #ebf8ff; }
  .meta { background: white; padding: 16px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 24px; }
  .meta p { margin: 4px 0; font-size: 14px; }
  .observations ul { background: white; padding: 20px 20px 20px 36px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
  .observations li { margin-bottom: 12px; font-size: 14px; line-height: 1.6; }
  .recommendation { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); font-size: 14px; line-height: 1.7; }
  .footer { text-align: center; margin-top: 40px; color: #718096; font-size: 12px; }
  .badge { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: bold; }
  .badge-ok { background: #c6f6d5; color: #276749; }
  .badge-warn { background: #fefcbf; color: #744210; }
  .badge-fail { background: #fed7d7; color: #9b2c2c; }
</style>
</head>
<body>

<div class="meta">
  <h1>📊 JMeter Performance Report — {{ date }}</h1>
  <p><strong>Rounds Analysed:</strong> {{ rounds|length }}</p>
  <p><strong>Generated:</strong> {{ generated_at }}</p>
  <p><strong>Tests:</strong> {{ rounds | map(attribute='test_name') | unique | join(', ') }}</p>
</div>

<!-- ====== SECTION 1: Per-Round Tables ====== -->
<h2>Section 1: Per-Round JMeter Results</h2>
{% for r, parsed in zip(rounds, parsed_results) %}
<h3>Round {{ r.round_number }} — {{ r.day_folder }}</h3>
<table>
  <thead>
    <tr>
      <th>Label</th><th># Samples</th><th>Average (ms)</th><th>Median (ms)</th>
      <th>90% Line (ms)</th><th>95% Line (ms)</th><th>99% Line (ms)</th>
      <th>Min (ms)</th><th>Max (ms)</th><th>Error %</th>
      <th>Throughput (req/s)</th><th>Received KB/s</th><th>Sent KB/s</th>
    </tr>
  </thead>
  <tbody>
    {% for row in parsed.label_rows %}
    <tr>
      <td>{{ row.label }}</td>
      <td>{{ row.sample_count | commaformat }}</td>
      <td>{{ row.avg_ms }}</td><td>{{ row.median_ms }}</td>
      <td>{{ row.p90_ms }}</td><td>{{ row.p95_ms }}</td><td>{{ row.p99_ms }}</td>
      <td>{{ row.min_ms }}</td><td>{{ row.max_ms }}</td>
      <td>{{ "%.2f"|format(row.error_pct) }}%</td>
      <td>{{ row.throughput_req_sec }}</td>
      <td>{{ row.received_kb_sec }}</td><td>{{ row.sent_kb_sec }}</td>
    </tr>
    {% endfor %}
    <tr class="total-row">
      <td>TOTAL</td>
      <td>{{ parsed.total.sample_count | commaformat }}</td>
      <td>{{ parsed.total.avg_ms }}</td><td>{{ parsed.total.median_ms }}</td>
      <td>{{ parsed.total.p90_ms }}</td><td>{{ parsed.total.p95_ms }}</td><td>{{ parsed.total.p99_ms }}</td>
      <td>{{ parsed.total.min_ms }}</td><td>{{ parsed.total.max_ms }}</td>
      <td>{{ "%.2f"|format(parsed.total.error_pct) }}%</td>
      <td>{{ parsed.total.throughput_req_sec }}</td>
      <td>{{ parsed.total.received_kb_sec }}</td><td>{{ parsed.total.sent_kb_sec }}</td>
    </tr>
  </tbody>
</table>
{% endfor %}

<!-- ====== SECTION 2: Consolidated Comparison ====== -->
<h2>Section 2: Consolidated Comparison</h2>
<table>
  <thead>
    <tr>
      <th>Metric</th>
      {% for r in rounds %}<th>Round {{ r.round_number }} ({{ r.day_folder.split('_')[2] if '_' in r.day_folder else '' }})</th>{% endfor %}
    </tr>
  </thead>
  <tbody>
    {% for row in comparison %}
    <tr>
      <td><strong>{{ row.metric }}</strong></td>
      {% for r in rounds %}<td>{{ row["Round " ~ r.round_number] }}</td>{% endfor %}
    </tr>
    {% endfor %}
  </tbody>
</table>

<!-- ====== SECTION 3: Key Observations ====== -->
<h2>Section 3: Key Observations</h2>
<div class="observations">
  <ul>
    {% for obs in observations %}
    <li>{{ obs }}</li>
    {% endfor %}
  </ul>
</div>

<!-- ====== SECTION 4: Recommendation ====== -->
<h2>Section 4: Recommendation</h2>
<div class="recommendation">
  <p>{{ recommendation }}</p>
</div>

<div class="footer">
  <p>Generated by Performance Test Execution &amp; Reporting MCP Server | {{ generated_at }}</p>
</div>

</body>
</html>
"""


def _render_html(
    date: str,
    rounds: list[RoundSummary],
    parsed_results: list[ParsedJtlResult],
    comparison: list[dict],
    observations: list[str],
    recommendation: str,
    generated_at: str,
) -> str:
    """Render the Jinja2 HTML template with all section data.

    Args:
        date: Report date string.
        rounds: Ordered round summaries.
        parsed_results: Corresponding parsed JTL results.
        comparison: Comparison table rows from _build_comparison.
        observations: Observation bullet strings from _build_observations.
        recommendation: Recommendation paragraph from _build_recommendation.
        generated_at: Human-readable generation timestamp.

    Returns:
        Rendered HTML string.
    """
    env = Environment(loader=BaseLoader(), autoescape=True)

    # Add zip and custom filter for comma-formatting large integers
    env.globals["zip"] = zip
    env.filters["commaformat"] = lambda v: f"{v:,}"

    template = env.from_string(_HTML_TEMPLATE)
    return template.render(
        date=date,
        rounds=rounds,
        parsed_results=parsed_results,
        comparison=comparison,
        observations=observations,
        recommendation=recommendation,
        generated_at=generated_at,
    )
