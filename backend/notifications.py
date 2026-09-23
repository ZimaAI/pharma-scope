"""Notification delivery adapters.

SMTP is opt-in and dry-run by default.  Every attempt returns a structured
result so the delivery record can distinguish queued, sent, dry-run and failed.
"""
from __future__ import annotations

import asyncio
import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage


@dataclass
class DeliveryResult:
    state: str
    attempts: int
    error_code: str | None = None
    message_id: str | None = None


class SMTPAdapter:
    def __init__(self, *, host: str | None = None, port: int | None = None, username: str | None = None, password: str | None = None, sender: str | None = None, enabled: bool | None = None, dry_run: bool | None = None, retries: int = 3):
        self.host = host or os.getenv("PH_SMTP_HOST", "")
        self.port = int(port or os.getenv("PH_SMTP_PORT", "587"))
        self.username = username or os.getenv("PH_SMTP_USER", "")
        self.password = password or os.getenv("PH_SMTP_PASSWORD", "")
        self.sender = sender or os.getenv("PH_SMTP_FROM", "")
        self.enabled = (os.getenv("PH_REAL_EMAIL_ENABLED", "false").lower() == "true") if enabled is None else enabled
        self.dry_run = (os.getenv("PH_SMTP_DRY_RUN", "true").lower() != "false") if dry_run is None else dry_run
        self.retries = max(1, min(int(retries), 5))

    @property
    def configured(self) -> bool:
        return bool(self.host and self.sender)

    async def send(self, *, recipient: str, subject: str, body: str, idempotency_key: str | None = None) -> DeliveryResult:
        if not self.enabled:
            return DeliveryResult("disabled", 0, "smtp_disabled")
        if not self.configured:
            return DeliveryResult("failed", 0, "smtp_not_configured")
        if self.dry_run:
            return DeliveryResult("dry_run", 1, message_id=idempotency_key)
        message = EmailMessage(); message["From"] = self.sender; message["To"] = recipient; message["Subject"] = subject; message["Message-ID"] = f"<{idempotency_key}@pharmascope>" if idempotency_key else __import__("email.utils").utils.make_msgid(); message.set_content(body)
        last: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                await asyncio.to_thread(self._send_sync, message)
                return DeliveryResult("sent", attempt, message_id=idempotency_key)
            except (OSError, smtplib.SMTPException) as exc:
                last = exc
                if attempt < self.retries: await asyncio.sleep(min(8, 2 ** (attempt - 1)))
        return DeliveryResult("failed", self.retries, "smtp_delivery_failed")

    def _send_sync(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self.host, self.port, timeout=20) as smtp:
            smtp.ehlo(); smtp.starttls(); smtp.ehlo()
            if self.username: smtp.login(self.username, self.password)
            smtp.send_message(message)
