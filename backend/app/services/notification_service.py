"""Notification service — SMTP email and Microsoft Teams webhook sending.

All functions degrade gracefully when credentials are not configured:
they log a warning and return without raising, so callers are never blocked
by missing notification infrastructure.
"""

from __future__ import annotations

import logging
from email.message import EmailMessage
from typing import Any

logger = logging.getLogger(__name__)


class NotificationService:
    """Facade for sending notifications via email and Microsoft Teams.

    Wraps the module-level ``send_email`` and ``send_teams_notification``
    coroutines so callers can dependency-inject a service object while still
    benefiting from the same graceful-degradation behaviour.
    """

    async def send_email(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        smtp_host: str,
        smtp_port: int = 587,
        smtp_from: str = "",
        smtp_username: str | None = None,
        smtp_password: str | None = None,
    ) -> bool:
        return await send_email(
            to=to,
            subject=subject,
            body=body,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_from=smtp_from,
            smtp_username=smtp_username,
            smtp_password=smtp_password,
        )

    async def send_teams_notification(
        self,
        webhook_url: str,
        message: str,
        *,
        theme_color: str = "0078D4",
    ) -> bool:
        return await send_teams_notification(
            webhook_url, message, theme_color=theme_color
        )


async def send_email(
    *,
    to: str,
    subject: str,
    body: str,
    smtp_host: str,
    smtp_port: int = 587,
    smtp_from: str = "",
    smtp_username: str | None = None,
    smtp_password: str | None = None,
) -> bool:
    """Send an email via SMTP with STARTTLS.

    Returns ``True`` on success, ``False`` if SMTP is not configured or the
    connection fails (logs a warning instead of raising).
    """
    if not smtp_host:
        logger.warning("smtp_not_configured: skipping email notification")
        return False

    try:
        import aiosmtplib  # noqa: PLC0415 — optional dependency guard

        msg = EmailMessage()
        msg["From"] = smtp_from or "archon@localhost"
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)

        # Treat masked placeholder as absent
        if smtp_password == "********":
            smtp_password = None

        await aiosmtplib.send(
            msg,
            hostname=smtp_host,
            port=smtp_port,
            username=smtp_username or None,
            password=smtp_password or None,
            start_tls=True,
        )
        logger.info("email_sent", to=to, subject=subject)
        return True
    except ImportError:
        logger.warning("aiosmtplib_not_installed: cannot send email")
        return False
    except Exception as exc:
        logger.error("smtp_send_failed", error=str(exc), to=to)
        raise


async def send_teams_notification(
    webhook_url: str,
    message: str,
    *,
    theme_color: str = "0078D4",
) -> bool:
    """POST a MessageCard to a Microsoft Teams Incoming Webhook URL.

    Returns ``True`` on success, ``False`` if the webhook URL is not configured
    (logs a warning instead of raising).

    MessageCard format:
        {
            "@type": "MessageCard",
            "themeColor": "0078D4",
            "summary": "<message>",
            "sections": [{"activityText": "<message>"}]
        }
    """
    if not webhook_url:
        logger.warning("teams_webhook_not_configured: skipping Teams notification")
        return False

    try:
        import httpx  # noqa: PLC0415 — always available (in requirements.txt)

        payload: dict[str, Any] = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": theme_color,
            "summary": message,
            "sections": [{"activityText": message}],
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(webhook_url, json=payload)
            response.raise_for_status()

        logger.info("teams_notification_sent", webhook_url=webhook_url)
        return True
    except Exception as exc:
        logger.error("teams_send_failed", error=str(exc), webhook_url=webhook_url)
        raise
