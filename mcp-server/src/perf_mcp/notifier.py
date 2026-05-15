"""
Teams and Slack webhook notifier with retry logic and fail-open behaviour.

Design decisions:
- Webhook URLs are read exclusively from environment variables (NFR-003).
- URLs are NEVER written to logs or terminal output (NFR-003-3).
- Webhook failure does NOT block report generation (FR-008-7).
- 3 retries with exponential backoff: 1s → 2s → 4s (FR-008-5).
- Each attempt times out at 12 seconds (FR-008-6).
- Terminal notification is always emitted regardless of webhook result (FR-007).
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime

import requests

from .models import KpiMetrics, NotificationStatus, RoundSummary

logger = logging.getLogger(__name__)

# Retry config per FR-008-5
_MAX_RETRIES = 3
_RETRY_BACKOFF_SECONDS = [1, 2]

# Per-attempt timeout per FR-008-6
_REQUEST_TIMEOUT_SECONDS = 12


def _ts() -> str:
    """Return current time as [HH:MM:SS] string for terminal notification format."""
    return datetime.now().strftime("%H:%M:%S")


def send_test_started_notification(
    notification_channel: str,
    test_name: str,
    job_id: str,
    round_number: int,
    script_path: str,
) -> dict[str, NotificationStatus]:
    """Send a 'test started' notification to configured channels.

    Emits a terminal notification unconditionally. Dispatches to Teams/Slack
    based on ``notification_channel`` and available env vars.

    Args:
        notification_channel: One of ``terminal`` | ``teams`` | ``slack`` | ``both``.
        test_name: Logical name of the test (e.g. "GET_RO_Number_Load").
        job_id: Unique job identifier.
        round_number: Round number for today.
        script_path: JMX script path on the VM.

    Returns:
        Dict mapping channel name to :class:`NotificationStatus`.
    """
    results: dict[str, NotificationStatus] = {}

    print(
        f"[{_ts()}] 🚀 TEST STARTED — "
        f"Test: {test_name} | Job: {job_id} | Round: {round_number}"
    )
    results["terminal"] = NotificationStatus(channel="terminal", delivered=True, attempts=1)

    if notification_channel in ("teams", "both"):
        results["teams"] = _send_teams_started(test_name, job_id, round_number, script_path)

    if notification_channel in ("slack", "both"):
        results["slack"] = _send_slack_started(test_name, job_id, round_number, script_path)

    return results


def send_test_completed_notification(
    notification_channel: str,
    test_name: str,
    job_id: str,
    metrics: KpiMetrics | None,
) -> dict[str, NotificationStatus]:
    """Send a 'test completed' notification to configured channels.

    Emits a terminal notification unconditionally. Dispatches to Teams/Slack
    based on ``notification_channel`` and available env vars.

    Args:
        notification_channel: One of ``terminal`` | ``teams`` | ``slack`` | ``both``.
        test_name: Logical name of the test.
        job_id: Unique job identifier.
        metrics: Parsed KPI metrics, or None if unavailable.

    Returns:
        Dict mapping channel name to :class:`NotificationStatus`.
    """
    results: dict[str, NotificationStatus] = {}

    if metrics:
        print(
            f"[{_ts()}] ✅ TEST COMPLETED — "
            f"Test: {test_name} | Requests: {metrics.total_requests:,} | "
            f"Errors: {metrics.error_rate_pct:.2f}% | Avg: {metrics.avg_response_ms:.0f}ms"
        )
    else:
        print(f"[{_ts()}] ✅ TEST COMPLETED — Test: {test_name} | Job: {job_id}")
    results["terminal"] = NotificationStatus(channel="terminal", delivered=True, attempts=1)

    if notification_channel in ("teams", "both"):
        results["teams"] = _send_teams_completed(test_name, job_id, metrics)

    if notification_channel in ("slack", "both"):
        results["slack"] = _send_slack_completed(test_name, job_id, metrics)

    return results


def send_report_notification(
    notification_channel: str,
    date: str,
    rounds_found: int,
    best_round: str,
    avg_response_trend: str,
    error_rate: float,
    report_path: str,
    round_summaries: list[RoundSummary] | None = None,
) -> dict[str, NotificationStatus]:
    """Send report-ready notifications to configured channels.

    Dispatches to Teams and/or Slack based on ``notification_channel`` value
    and available environment variables. Terminal notification is always emitted.
    Webhook failure is logged but never raises — report generation is unaffected.

    Args:
        notification_channel: One of ``terminal`` | ``teams`` | ``slack`` | ``both``.
        date: Report date string (YYYY-MM-DD).
        rounds_found: Number of test rounds run on this date.
        best_round: Label of the best-performing round (e.g. "Round 1").
        avg_response_trend: Human-readable trend description (e.g. "+3.5% degraded").
        error_rate: Weighted average error rate across all rounds (percentage).
        report_path: Full UNC/local path to the generated HTML report.
        round_summaries: Optional list of per-round summaries for detailed comparison.

    Returns:
        Dict mapping channel name to :class:`NotificationStatus`.

    Example:
        >>> statuses = send_report_notification(
        ...     notification_channel="both",
        ...     date="2026-04-29",
        ...     rounds_found=2,
        ...     best_round="Round 1",
        ...     avg_response_trend="stable",
        ...     error_rate=0.82,
        ...     report_path="\\\\\\\\vm-host\\\\PerfTest\\\\results\\\\DAILY_REPORT_2026-04-29.html",
        ... )
    """
    results: dict[str, NotificationStatus] = {}

    # Terminal is always emitted
    _notify_terminal(date, rounds_found, best_round, avg_response_trend, error_rate, report_path)
    results["terminal"] = NotificationStatus(channel="terminal", delivered=True, attempts=1)

    if notification_channel in ("teams", "both"):
        results["teams"] = _send_teams(date, rounds_found, best_round, avg_response_trend, error_rate, report_path, round_summaries)

    if notification_channel in ("slack", "both"):
        results["slack"] = _send_slack(date, rounds_found, best_round, avg_response_trend, error_rate, report_path, round_summaries)

    return results


# ---------------------------------------------------------------------------
# Terminal notification
# ---------------------------------------------------------------------------


def _notify_terminal(
    date: str,
    rounds_found: int,
    best_round: str,
    avg_response_trend: str,
    error_rate: float,
    report_path: str,
) -> None:
    """Print report summary to terminal in mandatory notification format.

    Args:
        date: Report date string.
        rounds_found: Total rounds in this report.
        best_round: Label of the best-performing round.
        avg_response_trend: Trend description.
        error_rate: Weighted average error rate.
        report_path: Path to generated HTML report.
    """
    print(
        f"[{_ts()}] ✅ REPORT READY — "
        f"Date: {date} | Rounds: {rounds_found} | Best: {best_round} | "
        f"Trend: {avg_response_trend} | Error Rate: {error_rate:.2f}%"
    )
    print(f"[{_ts()}] 📊 REPORT PATH — {report_path}")


# ---------------------------------------------------------------------------
# Teams — started
# ---------------------------------------------------------------------------


def _send_teams_started(
    test_name: str,
    job_id: str,
    round_number: int,
    script_path: str,
) -> NotificationStatus:
    """POST a test-started notification to Teams via webhook."""
    webhook_url = os.getenv("TEAMS_WEBHOOK_URL", "")
    if not webhook_url:
        logger.warning("TEAMS_WEBHOOK_URL not set — skipping Teams notification")
        print(f"[{_ts()}] ⚠️  NOTIFICATION SKIPPED — Channel: teams | Reason: TEAMS_WEBHOOK_URL not configured")
        return NotificationStatus(channel="teams", delivered=False, attempts=0, error="TEAMS_WEBHOOK_URL not set")

    payload = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "themeColor": "00B050",
        "summary": f"JMeter Test STARTED — {test_name}",
        "sections": [
            {
                "activityTitle": f"\U0001f680 JMeter Test STARTED — {test_name}",
                "facts": [
                    {"name": "Test Name", "value": test_name},
                    {"name": "Job ID", "value": job_id},
                    {"name": "Round", "value": str(round_number)},
                    {"name": "Started At", "value": _ts()},
                    {"name": "Script", "value": script_path},
                ],
            }
        ],
    }
    return _post_with_retry("teams", webhook_url, payload)


# ---------------------------------------------------------------------------
# Teams — completed
# ---------------------------------------------------------------------------


def _send_teams_completed(
    test_name: str,
    job_id: str,
    metrics: KpiMetrics | None,
) -> NotificationStatus:
    """POST a test-completed notification to Teams via webhook."""
    webhook_url = os.getenv("TEAMS_WEBHOOK_URL", "")
    if not webhook_url:
        logger.warning("TEAMS_WEBHOOK_URL not set — skipping Teams notification")
        print(f"[{_ts()}] ⚠️  NOTIFICATION SKIPPED — Channel: teams | Reason: TEAMS_WEBHOOK_URL not configured")
        return NotificationStatus(channel="teams", delivered=False, attempts=0, error="TEAMS_WEBHOOK_URL not set")

    facts = [
        {"name": "Test Name", "value": test_name},
        {"name": "Job ID", "value": job_id},
        {"name": "Completed At", "value": _ts()},
    ]
    if metrics:
        facts += [
            {"name": "Total Requests", "value": f"{metrics.total_requests:,}"},
            {"name": "Error Rate", "value": f"{metrics.error_rate_pct:.2f}%"},
            {"name": "Avg Response", "value": f"{metrics.avg_response_ms:.0f} ms"},
            {"name": "P90 / P95 / P99", "value": f"{metrics.p90_ms:.0f} / {metrics.p95_ms:.0f} / {metrics.p99_ms:.0f} ms"},
            {"name": "Min / Max", "value": f"{metrics.min_ms:.0f} / {metrics.max_ms:.0f} ms"},
            {"name": "Throughput", "value": f"{metrics.throughput_req_sec:.1f} req/s"},
        ]

    payload = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "themeColor": "0076D7",
        "summary": f"JMeter Test COMPLETED — {test_name}",
        "sections": [
            {
                "activityTitle": f"\u2705 JMeter Test COMPLETED — {test_name}",
                "facts": facts,
            }
        ],
    }
    return _post_with_retry("teams", webhook_url, payload)


# ---------------------------------------------------------------------------
# Teams — report
# ---------------------------------------------------------------------------


def _send_teams(
    date: str,
    rounds_found: int,
    best_round: str,
    avg_response_trend: str,
    error_rate: float,
    report_path: str,
    round_summaries: list[RoundSummary] | None = None,
) -> NotificationStatus:
    """POST a report notification to Teams via webhook.

    Reads ``TEAMS_WEBHOOK_URL`` from environment. If env var is not set,
    returns a failed status immediately without making any network call.

    Args:
        date: Report date.
        rounds_found: Total rounds.
        best_round: Best-performing round label.
        avg_response_trend: Trend description.
        error_rate: Average error rate.
        report_path: HTML report path.
        round_summaries: Optional per-round summary list for detailed metrics.

    Returns:
        :class:`NotificationStatus` with delivery result.
    """
    webhook_url = os.getenv("TEAMS_WEBHOOK_URL", "")
    if not webhook_url:
        logger.warning("TEAMS_WEBHOOK_URL not set — skipping Teams notification")
        print(f"[{_ts()}] ⚠️  NOTIFICATION SKIPPED — Channel: teams | Reason: TEAMS_WEBHOOK_URL not configured")
        return NotificationStatus(channel="teams", delivered=False, attempts=0, error="TEAMS_WEBHOOK_URL not set")

    facts = [
        {"name": "Rounds", "value": str(rounds_found)},
        {"name": "Best Round", "value": best_round},
        {"name": "Avg Response Trend", "value": avg_response_trend},
        {"name": "Error Rate", "value": f"{error_rate:.2f}%"},
        {"name": "Report", "value": report_path},
    ]

    if round_summaries:
        for rs in round_summaries:
            m = rs.metrics
            facts.append({
                "name": f"Round {rs.round_number} — {rs.test_name}",
                "value": (
                    f"Requests: {m.total_requests:,} | "
                    f"Avg: {m.avg_response_ms:.0f}ms | P95: {m.p95_ms:.0f}ms | "
                    f"Errors: {m.error_rate_pct:.2f}% | Throughput: {m.throughput_req_sec:.1f} req/s"
                ),
            })

    payload = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "themeColor": "0076D7",
        "summary": f"JMeter Performance Report \u2014 {date}",
        "sections": [
            {
                "activityTitle": f"\U0001f4ca JMeter Performance Report \u2014 {date}",
                "facts": facts,
            }
        ],
    }

    return _post_with_retry("teams", webhook_url, payload)


# ---------------------------------------------------------------------------
# Slack — started
# ---------------------------------------------------------------------------


def _send_slack_started(
    test_name: str,
    job_id: str,
    round_number: int,
    script_path: str,
) -> NotificationStatus:
    """POST a test-started notification to Slack via webhook."""
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_URL not set — skipping Slack notification")
        print(f"[{_ts()}] ⚠️  NOTIFICATION SKIPPED — Channel: slack | Reason: SLACK_WEBHOOK_URL not configured")
        return NotificationStatus(channel="slack", delivered=False, attempts=0, error="SLACK_WEBHOOK_URL not set")

    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"\U0001f680 JMeter Test STARTED", "emoji": True},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Test Name:*\n{test_name}"},
                    {"type": "mrkdwn", "text": f"*Round:*\n{round_number}"},
                    {"type": "mrkdwn", "text": f"*Job ID:*\n{job_id}"},
                    {"type": "mrkdwn", "text": f"*Started At:*\n{_ts()}"},
                ],
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Script:* `{script_path}`"},
            },
            {"type": "divider"},
        ]
    }
    return _post_with_retry("slack", webhook_url, payload)


# ---------------------------------------------------------------------------
# Slack — completed
# ---------------------------------------------------------------------------


def _send_slack_completed(
    test_name: str,
    job_id: str,
    metrics: KpiMetrics | None,
) -> NotificationStatus:
    """POST a test-completed notification to Slack via webhook."""
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_URL not set — skipping Slack notification")
        print(f"[{_ts()}] ⚠️  NOTIFICATION SKIPPED — Channel: slack | Reason: SLACK_WEBHOOK_URL not configured")
        return NotificationStatus(channel="slack", delivered=False, attempts=0, error="SLACK_WEBHOOK_URL not set")

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "\u2705 JMeter Test COMPLETED", "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Test Name:*\n{test_name}"},
                {"type": "mrkdwn", "text": f"*Job ID:*\n{job_id}"},
            ],
        },
    ]

    if metrics:
        blocks.append({
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Total Requests:*\n{metrics.total_requests:,}"},
                {"type": "mrkdwn", "text": f"*Error Rate:*\n{metrics.error_rate_pct:.2f}%"},
                {"type": "mrkdwn", "text": f"*Avg Response:*\n{metrics.avg_response_ms:.0f} ms"},
                {"type": "mrkdwn", "text": f"*Throughput:*\n{metrics.throughput_req_sec:.1f} req/s"},
                {"type": "mrkdwn", "text": f"*P90 / P95 / P99:*\n{metrics.p90_ms:.0f} / {metrics.p95_ms:.0f} / {metrics.p99_ms:.0f} ms"},
                {"type": "mrkdwn", "text": f"*Min / Max:*\n{metrics.min_ms:.0f} / {metrics.max_ms:.0f} ms"},
            ],
        })

    blocks.append({"type": "divider"})

    payload = {"blocks": blocks}
    return _post_with_retry("slack", webhook_url, payload)


# ---------------------------------------------------------------------------
# Slack — report
# ---------------------------------------------------------------------------


def _send_slack(
    date: str,
    rounds_found: int,
    best_round: str,
    avg_response_trend: str,
    error_rate: float,
    report_path: str,
    round_summaries: list[RoundSummary] | None = None,
) -> NotificationStatus:
    """POST a detailed report notification to Slack via webhook.

    Reads ``SLACK_WEBHOOK_URL`` from environment. If env var is not set,
    returns a failed status immediately without making any network call.

    Includes per-round KPI comparison table and key observations when
    ``round_summaries`` is provided.

    Args:
        date: Report date.
        rounds_found: Total rounds.
        best_round: Best-performing round label.
        avg_response_trend: Trend description.
        error_rate: Average error rate.
        report_path: HTML report path.
        round_summaries: Optional per-round summary list for detailed comparison.

    Returns:
        :class:`NotificationStatus` with delivery result.
    """
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_URL not set — skipping Slack notification")
        print(f"[{_ts()}] ⚠️  NOTIFICATION SKIPPED — Channel: slack | Reason: SLACK_WEBHOOK_URL not configured")
        return NotificationStatus(channel="slack", delivered=False, attempts=0, error="SLACK_WEBHOOK_URL not set")

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"\U0001f4ca JMeter Report \u2014 {date}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Rounds:* {rounds_found}"},
                {"type": "mrkdwn", "text": f"*Best Round:* {best_round}"},
                {"type": "mrkdwn", "text": f"*Avg Trend:* {avg_response_trend}"},
                {"type": "mrkdwn", "text": f"*Avg Error Rate:* {error_rate:.2f}%"},
            ],
        },
    ]

    # Per-round KPI comparison table
    if round_summaries:
        rows = ["*Round-by-Round KPI Summary:*"]
        rows.append("`{:<10} {:>10} {:>8} {:>8} {:>8} {:>8} {:>8}`".format(
            "Round", "Requests", "Avg(ms)", "P95(ms)", "P99(ms)", "Err%", "Tput"
        ))
        for rs in round_summaries:
            m = rs.metrics
            rows.append("`{:<10} {:>10,} {:>8.0f} {:>8.0f} {:>8.0f} {:>7.2f}% {:>7.1f}`".format(
                f"Round {rs.round_number}",
                m.total_requests,
                m.avg_response_ms,
                m.p95_ms,
                m.p99_ms,
                m.error_rate_pct,
                m.throughput_req_sec,
            ))
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(rows)},
        })

        # Key observations
        observations = _build_observations(round_summaries, avg_response_trend, error_rate)
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Key Observations:*\n" + observations},
        })

    blocks += [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Report:* `{report_path}`",
            },
        },
        {"type": "divider"},
    ]

    payload = {"blocks": blocks}
    return _post_with_retry("slack", webhook_url, payload)


def _build_observations(
    round_summaries: list[RoundSummary],
    avg_response_trend: str,
    avg_error_rate: float,
) -> str:
    """Build architect-level key observations bullet list from round summaries.

    Args:
        round_summaries: Ordered list of round summaries.
        avg_response_trend: Trend label (stable / degraded / improved).
        avg_error_rate: Weighted average error rate across all rounds.

    Returns:
        Multi-line bullet string for Slack mrkdwn.
    """
    bullets: list[str] = []
    first = round_summaries[0].metrics
    last = round_summaries[-1].metrics
    n = len(round_summaries)

    # Trend
    delta_pct = ((last.avg_response_ms - first.avg_response_ms) / max(first.avg_response_ms, 1)) * 100
    if abs(delta_pct) < 5:
        bullets.append(f"• Avg response time is *stable* across {n} round(s) ({first.avg_response_ms:.0f}ms → {last.avg_response_ms:.0f}ms, {delta_pct:+.1f}%)")
    elif delta_pct > 0:
        bullets.append(f"• Avg response time *degraded* by {delta_pct:.1f}% from Round 1 ({first.avg_response_ms:.0f}ms) to Round {n} ({last.avg_response_ms:.0f}ms)")
    else:
        bullets.append(f"• Avg response time *improved* by {abs(delta_pct):.1f}% from Round 1 ({first.avg_response_ms:.0f}ms) to Round {n} ({last.avg_response_ms:.0f}ms)")

    # P95/P99 analysis
    p95_delta = ((last.p95_ms - first.p95_ms) / max(first.p95_ms, 1)) * 100
    p99_delta = ((last.p99_ms - first.p99_ms) / max(first.p99_ms, 1)) * 100
    bullets.append(
        f"• P95 latency: {first.p95_ms:.0f}ms → {last.p95_ms:.0f}ms ({p95_delta:+.1f}%); "
        f"P99 latency: {first.p99_ms:.0f}ms → {last.p99_ms:.0f}ms ({p99_delta:+.1f}%)"
    )

    # Max response time
    max_round = max(round_summaries, key=lambda r: r.metrics.max_ms)
    bullets.append(
        f"• Peak (max) response time was *{max_round.metrics.max_ms:.0f}ms* in Round {max_round.round_number} "
        f"— monitor for outlier transactions exceeding SLA"
    )

    # Error rate
    if avg_error_rate < 0.1:
        bullets.append(f"• Error rate is excellent at {avg_error_rate:.2f}% average — all rounds within acceptable threshold")
    elif avg_error_rate < 1.0:
        bullets.append(f"• Error rate is acceptable at {avg_error_rate:.2f}% average — review error logs for root cause")
    else:
        bullets.append(f"• ⚠️ Error rate is elevated at {avg_error_rate:.2f}% average — immediate investigation recommended")

    # Throughput stability
    tputs = [r.metrics.throughput_req_sec for r in round_summaries]
    tput_variance = (max(tputs) - min(tputs)) / max(max(tputs), 1) * 100
    if tput_variance < 5:
        bullets.append(f"• Throughput is stable across rounds (range: {min(tputs):.1f}–{max(tputs):.1f} req/s, variance {tput_variance:.1f}%)")
    else:
        bullets.append(f"• Throughput variance is {tput_variance:.1f}% (range: {min(tputs):.1f}–{max(tputs):.1f} req/s) — investigate resource contention between rounds")

    # Root cause hypothesis if degrading
    if delta_pct > 10:
        bullets.append(
            f"• Root cause hypothesis: sustained load may be exhausting connection pool or DB query plan cache "
            f"— compare thread counts and DB slow query logs across rounds"
        )

    return "\n".join(bullets)


# ---------------------------------------------------------------------------
# Shared retry logic
# ---------------------------------------------------------------------------


def _post_with_retry(channel: str, webhook_url: str, payload: dict) -> NotificationStatus:
    """POST JSON payload to webhook URL with exponential backoff retry.

    Retries up to 3 times on network errors or non-2xx responses.
    Each attempt times out at 12 seconds.
    Webhook URL is NEVER written to logs.

    Args:
        channel: Channel name for logging (teams | slack).
        webhook_url: Full webhook URL (from env var — not logged).
        payload: JSON payload dict to POST.

    Returns:
        :class:`NotificationStatus` with delivery result and attempt count.
    """
    last_error: str = ""

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = requests.post(
                webhook_url,
                json=payload,
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            if response.status_code in (200, 201, 202):
                print(f"[{_ts()}] ✅ NOTIFICATION SENT — Channel: {channel} | Status: delivered")
                logger.info("Notification delivered to %s on attempt %d", channel, attempt)
                return NotificationStatus(channel=channel, delivered=True, attempts=attempt)
            else:
                last_error = f"HTTP {response.status_code}"
                logger.warning(
                    "Webhook %s returned non-2xx on attempt %d: %s",
                    channel,
                    attempt,
                    response.status_code,
                )

        except requests.exceptions.Timeout:
            last_error = f"Timeout after {_REQUEST_TIMEOUT_SECONDS}s"
            logger.warning("Webhook %s timed out on attempt %d", channel, attempt)

        except requests.exceptions.ConnectionError as exc:
            last_error = "Connection error"
            logger.warning("Webhook %s connection error on attempt %d: %s", channel, attempt, exc)

        except Exception as exc:
            last_error = f"Unexpected error: {type(exc).__name__}"
            logger.error(
                "Unexpected error posting to %s on attempt %d: %s",
                channel,
                attempt,
                exc,
                exc_info=True,
            )

        # Backoff before next retry (skip sleep after final attempt)
        if attempt < _MAX_RETRIES:
            backoff = _RETRY_BACKOFF_SECONDS[attempt - 1]
            logger.debug("Retrying %s in %ds (attempt %d/%d)", channel, backoff, attempt, _MAX_RETRIES)
            time.sleep(backoff)

    print(f"[{_ts()}] ❌ NOTIFICATION FAILED — Channel: {channel} | Error: {last_error}")
    logger.error(
        "All %d notification attempts failed for channel %s. Last error: %s",
        _MAX_RETRIES,
        channel,
        last_error,
    )
    return NotificationStatus(
        channel=channel,
        delivered=False,
        attempts=_MAX_RETRIES,
        error=last_error,
    )
