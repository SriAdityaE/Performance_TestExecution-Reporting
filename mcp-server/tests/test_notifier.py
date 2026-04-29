"""
Tests for notifier.py.

Coverage targets:
  - Happy path: terminal always delivered, Teams success, Slack success
  - Unhappy: missing env var, HTTP 500 from webhook, connection error,
             timeout, all retries exhausted, both channels fail
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from perf_mcp.notifier import send_report_notification

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_NOTIF_KWARGS = dict(
    notification_channel="terminal",
    date="2026-04-29",
    rounds_found=2,
    best_round="Round 1",
    avg_response_trend="stable",
    error_rate=0.82,
    report_path="L:\\Testlogfiles\\MCP_Testlogfiles_entry\\results\\DAILY_REPORT_2026-04-29.html",
)


# ---------------------------------------------------------------------------
# Happy path tests
# ---------------------------------------------------------------------------

class TestNotifierHappyPath:
    def test_terminal_always_delivered(self):
        result = send_report_notification(**_NOTIF_KWARGS)
        assert result["terminal"].delivered is True
        assert result["terminal"].attempts == 1

    def test_terminal_only_no_webhook_called(self):
        with patch("perf_mcp.notifier.requests.post") as mock_post:
            send_report_notification(**_NOTIF_KWARGS)
            mock_post.assert_not_called()

    def test_teams_success(self, monkeypatch):
        monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://fake.webhook/teams")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("perf_mcp.notifier.requests.post", return_value=mock_resp):
            result = send_report_notification(**{**_NOTIF_KWARGS, "notification_channel": "teams"})
        assert result["teams"].delivered is True
        assert result["teams"].attempts == 1

    def test_slack_success(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/fake")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("perf_mcp.notifier.requests.post", return_value=mock_resp):
            result = send_report_notification(**{**_NOTIF_KWARGS, "notification_channel": "slack"})
        assert result["slack"].delivered is True

    def test_both_channels_success(self, monkeypatch):
        monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://fake.webhook/teams")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/fake")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("perf_mcp.notifier.requests.post", return_value=mock_resp):
            result = send_report_notification(**{**_NOTIF_KWARGS, "notification_channel": "both"})
        assert result["teams"].delivered is True
        assert result["slack"].delivered is True


# ---------------------------------------------------------------------------
# Unhappy path tests
# ---------------------------------------------------------------------------

class TestNotifierUnhappyPath:
    def test_teams_no_env_var_skipped(self, monkeypatch):
        monkeypatch.delenv("TEAMS_WEBHOOK_URL", raising=False)
        result = send_report_notification(**{**_NOTIF_KWARGS, "notification_channel": "teams"})
        assert result["teams"].delivered is False
        assert result["teams"].attempts == 0
        assert "not set" in result["teams"].error

    def test_slack_no_env_var_skipped(self, monkeypatch):
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        result = send_report_notification(**{**_NOTIF_KWARGS, "notification_channel": "slack"})
        assert result["slack"].delivered is False
        assert result["slack"].attempts == 0

    def test_teams_http_500_retries_exhausted(self, monkeypatch):
        monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://fake.webhook/teams")
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch("perf_mcp.notifier.requests.post", return_value=mock_resp):
            with patch("perf_mcp.notifier.time.sleep"):  # Skip backoff delay in tests
                result = send_report_notification(**{**_NOTIF_KWARGS, "notification_channel": "teams"})
        assert result["teams"].delivered is False
        assert result["teams"].attempts == 3

    def test_teams_connection_error_retries_exhausted(self, monkeypatch):
        monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://fake.webhook/teams")
        with patch("perf_mcp.notifier.requests.post", side_effect=requests.exceptions.ConnectionError("refused")):
            with patch("perf_mcp.notifier.time.sleep"):
                result = send_report_notification(**{**_NOTIF_KWARGS, "notification_channel": "teams"})
        assert result["teams"].delivered is False
        assert "Connection error" in result["teams"].error

    def test_teams_timeout_error(self, monkeypatch):
        monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://fake.webhook/teams")
        with patch("perf_mcp.notifier.requests.post", side_effect=requests.exceptions.Timeout()):
            with patch("perf_mcp.notifier.time.sleep"):
                result = send_report_notification(**{**_NOTIF_KWARGS, "notification_channel": "teams"})
        assert result["teams"].delivered is False
        assert "Timeout" in result["teams"].error

    def test_webhook_url_never_in_terminal_output(self, monkeypatch, capsys):
        """Webhook URL must NEVER appear in printed output (NFR-003-3)."""
        secret_url = "https://secret-webhook.example.com/super-secret-token"
        monkeypatch.setenv("TEAMS_WEBHOOK_URL", secret_url)
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch("perf_mcp.notifier.requests.post", return_value=mock_resp):
            with patch("perf_mcp.notifier.time.sleep"):
                send_report_notification(**{**_NOTIF_KWARGS, "notification_channel": "teams"})
        captured = capsys.readouterr()
        assert secret_url not in captured.out
        assert secret_url not in captured.err

    def test_both_channels_fail_terminal_still_delivered(self, monkeypatch):
        """Webhook failure must not affect terminal delivery (FR-008-7)."""
        monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://fake.webhook/teams")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/fake")
        with patch("perf_mcp.notifier.requests.post", side_effect=Exception("Network down")):
            with patch("perf_mcp.notifier.time.sleep"):
                result = send_report_notification(**{**_NOTIF_KWARGS, "notification_channel": "both"})
        assert result["terminal"].delivered is True
        assert result["teams"].delivered is False
        assert result["slack"].delivered is False

    def test_202_accepted_is_success(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/fake")
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        with patch("perf_mcp.notifier.requests.post", return_value=mock_resp):
            result = send_report_notification(**{**_NOTIF_KWARGS, "notification_channel": "slack"})
        assert result["slack"].delivered is True

