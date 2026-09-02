"""Emailing a report.

Delivery is deliberately isolated from generation. A wrong SMTP password should
cost the shop an email, not the week's report.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from pathlib import Path

from lbos.settings import Settings


def send_report(
    settings: Settings, subject: str, body: str, attachment: Path | None = None
) -> tuple[str, str]:
    """Try to email a report. Returns ``(status, detail)`` and never raises."""
    if not settings.email_configured:
        return "skipped", "Email is not set up (SMTP host, from address or recipient missing)."

    try:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = settings.smtp_from
        message["To"] = settings.report_email_to
        message.set_content(body)

        if attachment and attachment.exists():
            message.add_attachment(
                attachment.read_bytes(),
                maintype="text",
                subtype="plain",
                filename=attachment.name,
            )

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_user and settings.smtp_password:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
    except Exception as exc:
        return "failed", f"{type(exc).__name__}: {exc}"

    return "sent", f"Sent to {settings.report_email_to}."
