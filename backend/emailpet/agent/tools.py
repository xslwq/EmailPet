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
    """邮件操作工具集合，封装 IMAP 和 SMTP 操作供 LangGraph 节点使用。"""
    def __init__(self, imap: IMAPClient, smtp: SMTPClient) -> None:
        self.imap = imap
        self.smtp = smtp

    async def reply(self, email: Email, body: str) -> ToolResult:
        """发送回复给原始发件人，然后将原邮件标记为已读。

        Args:
            email: 原始邮件对象
            body: 回复正文

        Returns:
            ToolResult，状态为 "sent" 或 "error"
        """
        try:
            await self.smtp.send(
                to_addr=email.from_address,
                subject=_reply_subject(email.subject),
                body=body,
            )
        except Exception as e:  # noqa: BLE001 - 向用户展示错误信息，而不是崩溃
            logger.warning("reply failed for uid=%s: %s", email.uid, e)
            return {"status": "error", "message": str(e)}

        # 尽力而为标记已读；即使标记失败也不要让整个回复失败
        try:
            await self.imap.mark_read(email.uid)
        except Exception as e:  # noqa: BLE001
            logger.warning("mark_read after reply failed for uid=%s: %s", email.uid, e)

        return {"status": "sent"}

    async def archive(self, email: Email) -> ToolResult:
        """归档邮件。

        Args:
            email: 邮件对象

        Returns:
            ToolResult，状态为 "archived" 或 "error"
        """
        try:
            await self.imap.archive(email.uid)
        except Exception as e:  # noqa: BLE001
            logger.warning("archive failed for uid=%s: %s", email.uid, e)
            return {"status": "error", "message": str(e)}
        return {"status": "archived"}

    async def mark_read(self, email: Email) -> ToolResult:
        """将邮件标记为已读。

        Args:
            email: 邮件对象

        Returns:
            ToolResult，状态为 "read" 或 "error"
        """
        try:
            await self.imap.mark_read(email.uid)
        except Exception as e:  # noqa: BLE001
            logger.warning("mark_read failed for uid=%s: %s", email.uid, e)
            return {"status": "error", "message": str(e)}
        return {"status": "read"}


def _reply_subject(original: str) -> str:
    """添加 'Re: ' 前缀（如果还没有）。"""
    s = original.strip()
    if s.lower().startswith("re:"):
        return s
    return f"Re: {s}"
