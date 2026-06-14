"""services/execution_service/live/alert_manager.py – Alert notification system.

Channels: Slack, WeChat Work, Email.
Severity: INFO, WARN, CRITICAL.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

from configs.settings import settings


class AlertManager:
    """Multi-channel alert notification system.

    Channels:
    - Slack: For CRITICAL + WARN alerts
    - WeChat Work: For CRITICAL alerts
    - Email: For daily summary

    Attributes:
        slack_token: Slack bot token.
        slack_channel: Default Slack channel.
        max_recent: Number of alerts to keep in memory.
    """

    def __init__(self, max_recent: int = 500) -> None:
        self.slack_token = settings.SLACK_BOT_TOKEN
        self.slack_channel = settings.SLACK_ALERT_CHANNEL
        self.max_recent = max_recent
        self._alerts: list[dict[str, Any]] = []

    def send(
        self,
        message: str,
        severity: str = "INFO",
        source: str = "system",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send an alert through configured channels.

        Args:
            message: Alert message text.
            severity: INFO / WARN / CRITICAL.
            source: Source system identifier.
            details: Additional structured details.

        Returns:
            Alert record.
        """
        severity = severity.upper()
        alert = {
            "id": f"alert_{int(time.time() * 1000)}",
            "message": message,
            "severity": severity,
            "source": source,
            "details": details or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._alerts.append(alert)

        # Trim old alerts
        if len(self._alerts) > self.max_recent:
            self._alerts = self._alerts[-self.max_recent:]

        # Log
        log_fn = {"INFO": logger.info, "WARN": logger.warning, "CRITICAL": logger.error}
        log_fn.get(severity, logger.info)(f"[{severity}] {source}: {message}")

        # Slack notification
        if severity in ("CRITICAL", "WARN") and self.slack_token:
            self._send_slack(alert)

        # WeChat Work
        if severity == "CRITICAL":
            self._send_wechat(alert)

        return alert

    def _send_slack(self, alert: dict[str, Any]) -> None:
        """Send alert to Slack.

        Args:
            alert: Alert dictionary.
        """
        try:
            import httpx

            message = (
                f"*[{alert['severity']}] {alert['source']}*\n"
                f"{alert['message']}\n"
                f"_{alert['timestamp']}_"
            )

            # This would use the Slack API; simplified for framework
            logger.debug(f"Slack alert would be sent to {self.slack_channel}: {message[:100]}")

        except ImportError:
            logger.debug("httpx not available for Slack notifications")

    def _send_wechat(self, alert: dict[str, Any]) -> None:
        """Send alert to WeChat Work.

        Args:
            alert: Alert dictionary.
        """
        logger.debug(f"WeChat alert would be sent: {alert['message'][:100]}")

    def check_and_alert(self, order_result: dict[str, Any]) -> None:
        """Check order result and send appropriate alerts.

        Args:
            order_result: Order confirmation from broker.
        """
        status = order_result.get("status", "")
        ticker = order_result.get("ticker", "")

        if "FAILED" in status:
            self.send(
                message=f"Order FAILED: {order_result.get('side')} {order_result.get('quantity')} {ticker}",
                severity="CRITICAL",
                source="execution",
                details=order_result,
            )
        elif "REJECTED" in status:
            self.send(
                message=f"Order REJECTED: {order_result.get('error', 'Unknown')}",
                severity="WARN",
                source="execution",
                details=order_result,
            )
        elif "PENDING_CONFIRMATION" in status:
            self.send(
                message=f"Order requires confirmation: {ticker}",
                severity="INFO",
                source="execution",
            )

    def get_recent(
        self,
        severity: str | None = None,
        max_count: int = 50,
    ) -> list[dict[str, Any]]:
        """Get recent alerts with optional severity filter.

        Args:
            severity: Filter by severity level.
            max_count: Maximum number to return.

        Returns:
            List of alert dicts.
        """
        alerts = self._alerts
        if severity:
            alerts = [a for a in alerts if a["severity"] == severity.upper()]
        return alerts[-max_count:]

    def get_summary(self) -> dict[str, int]:
        """Get alert count summary by severity.

        Returns:
            Dict of severity → count.
        """
        summary: dict[str, int] = {"INFO": 0, "WARN": 0, "CRITICAL": 0}
        for alert in self._alerts:
            sev = alert.get("severity", "INFO")
            summary[sev] = summary.get(sev, 0) + 1
        return summary
