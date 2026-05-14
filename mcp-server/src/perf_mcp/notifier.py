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

from .models import NotificationStatus

logger = logging.getLogger(__name__)

# Retry config per FR-008-5
_MAX_RETRIES = 3
_RETRY_BACKOFF_SECONDS = [1, 2]

# Per-attempt timeout per FR-008-6
_REQUEST_TIMEOUT_SECONDS = 12


def _ts() -> str:
    """Return current time as [HH:MM:SS] string for terminal notification format."""
    return datetime.now().strftime("%H:%M:%S")


def send_report_notification(
    notification_channel: str,
    date: str,
    rounds_found: int,
    best_round: str,
    avg_response_trend: str,
    error_rate: float,
    report_path: str,
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
        results["teams"] = _send_teams(date, rounds_found, best_round, avg_response_trend, error_rate, report_path)

    if notification_channel in ("slack", "both"):
        results["slack"] = _send_slack(date, rounds_found, best_round, avg_response_trend, error_rate, report_path)

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
# Teams
# ---------------------------------------------------------------------------


def _send_teams(
    date: str,
    rounds_found: int,
    best_round: str,
    avg_response_trend: str,
    error_rate: float,
    report_path: str,
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

    Returns:
        :class:`NotificationStatus` with delivery result.
    """
    webhook_url = os.getenv("TEAMS_WEBHOOK_URL", "")
    if not webhook_url:
        logger.warning("TEAMS_WEBHOOK_URL not set — skipping Teams notification")
        print(f"[{_ts()}] ⚠️  NOTIFICATION SKIPPED — Channel: teams | Reason: TEAMS_WEBHOOK_URL not configured")
        return NotificationStatus(channel="teams", delivered=False, attempts=0, error="TEAMS_WEBHOOK_URL not set")

    payload = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "themeColor": "0076D7",
        "summary": f"JMeter Performance Report \u2014 {date}",
        "sections": [
            {
                "activityTitle": f"\U0001f4ca JMeter Performance Report \u2014 {date}",
                "facts": [
                    {"name": "Rounds", "value": str(rounds_found)},
                    {"name": "Best Round", "value": best_round},
                    {"name": "Avg Response Trend", "value": avg_response_trend},
                    {"name": "Error Rate", "value": f"{error_rate:.2f}%"},
                    {"name": "Report", "value": report_path},
                ],
            }
        ],
    }

    return _post_with_retry("teams", webhook_url, payload)


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------


def _send_slack(
    date: str,
    rounds_found: int,
    best_round: str,
    avg_response_trend: str,
    error_rate: float,
    report_path: str,
) -> NotificationStatus:
    """POST a report notification to Slack via webhook.

    Reads ``SLACK_WEBHOOK_URL`` from environment. If env var is not set,
    returns a failed status immediately without making any network call.

    Args:
        date: Report date.
        rounds_found: Total rounds.
        best_round: Best-performing round label.
        avg_response_trend: Trend description.
        error_rate: Average error rate.
        report_path: HTML report path.

    Returns:
        :class:`NotificationStatus` with delivery result.
    """
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_URL not set — skipping Slack notification")
        print(f"[{_ts()}] ⚠️  NOTIFICATION SKIPPED — Channel: slack | Reason: SLACK_WEBHOOK_URL not configured")
        return NotificationStatus(channel="slack", delivered=False, attempts=0, error="SLACK_WEBHOOK_URL not set")

    payload = {
        "blocks": [
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
                    {"type": "mrkdwn", "text": f"*Error Rate:* {error_rate:.2f}%"},
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Report:* `{report_path}`",
                },
            },
            {"type": "divider"},
        ]
    }

    return _post_with_retry("slack", webhook_url, payload)


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
