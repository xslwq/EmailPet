"""SMTP client wrapping stdlib smtplib for async use.
"""
from __future__ import annotations

import asyncio
import smtplib
from email.header import Header
from email.mime.text import MIMEText


class SMTPClient:
    """SMTP 发送客户端（同步实现，异步包装）。

    职责：通过 SMTP SSL 发送邮件。
    用法：send() 发送单封邮件，每次发送建立新连接。
    """
    def __init__(self, host: str, port: int, username: str, password: str) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password

    async def send(self, to_addr: str, subject: str, body: str) -> None:
        """异步发送邮件（通过 asyncio.to_thread 包装同步实现）。"""
        await asyncio.to_thread(self._send_sync, to_addr, subject, body)

    def _send_sync(self, to_addr: str, subject: str, body: str) -> None:
        """同步发送邮件实现（SMTP SSL）。

        设计：每次发送建立新连接，失败时 quit 不抛异常。
        """
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
                # quit 失败不影响发送结果，吞掉异常
                pass

    async def close(self) -> None:
        """关闭连接（无操作：每次 send 用独立连接）。"""
        # 无持久连接，每次 send 建立新 SSL 会话
        return
