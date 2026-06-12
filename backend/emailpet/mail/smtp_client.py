"""SMTP client wrapping stdlib smtplib for async use.

See docs/modules/backend/emailpet/mail/smtp_client.md for full module doc.
"""
from __future__ import annotations

import asyncio
import smtplib
from email.header import Header
from email.mime.text import MIMEText


class SMTPClient:
    def __init__(self, host: str, port: int, username: str, password: str) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password

    async def send(self, to_addr: str, subject: str, body: str) -> None:
        await asyncio.to_thread(self._send_sync, to_addr, subject, body)

    def _send_sync(self, to_addr: str, subject: str, body: str) -> None:
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = self.username
        msg["To"] = to_addr
        msg["Subject"] = Header(subject, "utf-8")
        smtp = smtplib.SMTP_SSL(self.host, self.port, timeout=30)
        try:
            smtp.login(self.username, self.password)
            smtp.sendmail(self.username, [to_addr], msg.as_string())
        finally:
            try:
                smtp.quit()
            except (smtplib.SMTPException, OSError):
                pass

    async def close(self) -> None:
        # No persistent connection — each send opens its own SSL session.
        return
