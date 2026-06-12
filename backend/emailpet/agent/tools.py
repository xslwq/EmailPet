"""Agent tools — wrap IMAP/SMTP for use by LangGraph nodes.

See docs/modules/backend/emailpet/agent/tools.md for full module doc.
"""
from __future__ import annotations

import logging
from typing import TypedDict

from emailpet.mail.imap_client import IMAPClient
from emailpet.mail.models import Email
from emailpet.mail.smtp_client import SMTPClient

logger = logging.getLogger(__name__)


class ToolResult(TypedDict, total=False):
    status: str           # "sent" / "archived" / "read" / "error"
    message: str          # only for error


class AgentTools:
    def __init__(self, imap: IMAPClient, smtp: SMTPClient) -> None:
        self.imap = imap
        self.smtp = smtp

    async def reply(self, email: Email, body: str) -> ToolResult:
        """Send a reply to the original sender, then mark the original as read."""
        try:
            await self.smtp.send(
                to_addr=email.from_address,
                subject=_reply_subject(email.subject),
                body=body,
            )
        except Exception as e:  # noqa: BLE001 - surface message to user, not crash
            logger.warning("reply failed for uid=%s: %s", email.uid, e)
            return {"status": "error", "message": str(e)}

        # Best-effort mark-read; don't fail the whole reply if marking fails.
        try:
            await self.imap.mark_read(email.uid)
        except Exception as e:  # noqa: BLE001
            logger.warning("mark_read after reply failed for uid=%s: %s", email.uid, e)

        return {"status": "sent"}

    async def archive(self, email: Email) -> ToolResult:
        try:
            await self.imap.archive(email.uid)
        except Exception as e:  # noqa: BLE001
            logger.warning("archive failed for uid=%s: %s", email.uid, e)
            return {"status": "error", "message": str(e)}
        return {"status": "archived"}

    async def mark_read(self, email: Email) -> ToolResult:
        try:
            await self.imap.mark_read(email.uid)
        except Exception as e:  # noqa: BLE001
            logger.warning("mark_read failed for uid=%s: %s", email.uid, e)
            return {"status": "error", "message": str(e)}
        return {"status": "read"}


def _reply_subject(original: str) -> str:
    """Add 'Re: ' prefix if not already there."""
    s = original.strip()
    if s.lower().startswith("re:"):
        return s
    return f"Re: {s}"
