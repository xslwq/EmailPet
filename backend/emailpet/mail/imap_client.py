"""Async IMAP client wrapper around aioimaplib.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.header import decode_header
from email.message import Message
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from typing import Optional

import aioimaplib
from bs4 import BeautifulSoup

from .models import Email

logger = logging.getLogger(__name__)


class IMAPAuthError(Exception):
    """IMAP 认证失败。"""


class IMAPCommandError(Exception):
    """IMAP 命令返回非 OK 响应。"""

    def __init__(self, command: str, response: object) -> None:
        super().__init__(f"IMAP {command} failed: {response!r}")
        self.command = command
        self.response = response


class IMAPClient:
    """异步 IMAP 客户端（基于 aioimaplib）。

    职责：连接 IMAP 服务器、拉取新邮件、标记已读、归档。
    用法：connect() 建立连接，poll() 拉取新邮件，archive() 归档邮件。
    """
    def __init__(self, host: str, port: int, username: str, password: str) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self._client: Optional[aioimaplib.IMAP4_SSL] = None

    async def connect(self) -> None:
        """建立 IMAP SSL 连接并登录（幂等）。"""
        if self._client is not None:
            return
        client = aioimaplib.IMAP4_SSL(host=self.host, port=self.port, timeout=30)
        await client.wait_hello_from_server()
        status, _ = await client.login(self.username, self.password)
        if status != "OK":
            raise IMAPAuthError(f"login failed for {self.username}")
        self._client = client

    async def close(self) -> None:
        """登出并关闭连接（失败不抛异常）。"""
        if self._client is None:
            return
        try:
            await self._client.logout()
        except Exception:
            logger.warning("imap logout failed", exc_info=True)
        self._client = None

    async def poll(self, seen_uids: set[int]) -> tuple[list[Email], list[int]]:
        """拉取 INBOX 中未读且未处理过的新邮件。

        返回：
            (parsed_emails, processed_uids)
            - parsed_emails: 成功解析的邮件列表
            - processed_uids: 所有处理过的 UID（包括解析失败的，调用方应全部标记为已处理）

        设计：解析失败的邮件也标记为已处理，避免无限重试损坏邮件。
        """
        await self.connect()
        assert self._client is not None
        status, _ = await self._client.select("INBOX")
        if status != "OK":
            raise IMAPCommandError("SELECT", status)
        status, lines = await self._client.uid_search("UNSEEN")
        if status != "OK":
            raise IMAPCommandError("UID SEARCH", lines)
        # lines[0] 格式示例：b"1 2 3" 或 b""
        if not lines or not lines[0]:
            return [], []
        first = lines[0]
        if isinstance(first, (bytes, bytearray)):
            first = bytes(first).decode("ascii", errors="ignore")
        uids: list[int] = []
        for tok in first.strip().split():
            try:
                uids.append(int(tok))
            except ValueError:
                continue
        # 过滤掉已处理过的 UID
        new_uids = [u for u in uids if u not in seen_uids]
        out: list[Email] = []
        processed: list[int] = []
        for uid in new_uids:
            try:
                email_obj = await self._fetch_one(uid)
                out.append(email_obj)
                processed.append(uid)
            except Exception:
                logger.warning("failed to fetch/parse uid=%s", uid, exc_info=True)
                # 解析失败也标记为已处理，避免无限重试
                processed.append(uid)
        return out, processed

    async def _fetch_one(self, uid: int) -> Email:
        """拉取单封邮件的完整 RFC822 内容并解析。"""
        assert self._client is not None
        status, lines = await self._client.uid("FETCH", str(uid), "(RFC822)")
        if status != "OK":
            raise IMAPCommandError("UID FETCH", lines)
        raw = _extract_raw(lines)
        msg = BytesParser().parsebytes(raw)
        return _parse_email(uid, msg)

    async def archive(self, uid: int) -> None:
        """归档邮件：COPY 到 Archive 文件夹 + 删除原邮件。

        降级策略：Archive 文件夹不存在时，仅标记为已读。
        """
        await self.connect()
        assert self._client is not None
        status, _ = await self._client.uid("COPY", str(uid), "Archive")
        if status == "OK":
            store_status, store_resp = await self._client.uid(
                "STORE", str(uid), "+FLAGS (\\Deleted)"
            )
            if store_status != "OK":
                # COPY 已成功，若标记删除失败则抛异常（避免 INBOX 留重复）
                raise IMAPCommandError("UID STORE", store_resp)
            expunge_status, expunge_resp = await self._client.expunge()
            if expunge_status != "OK":
                raise IMAPCommandError("EXPUNGE", expunge_resp)
        else:
            logger.info("archive folder unavailable, fallback to mark_read for uid=%s", uid)
            await self._client.uid("STORE", str(uid), "+FLAGS (\\Seen)")

    async def mark_read(self, uid: int) -> None:
        """标记邮件为已读。"""
        await self.connect()
        assert self._client is not None
        await self._client.uid("STORE", str(uid), "+FLAGS (\\Seen)")


def _extract_raw(lines: list) -> bytes:
    """从 aioimaplib FETCH 响应中提取原始邮件内容。

    aioimaplib 返回混合格式（帧 + 内容），启发式识别：
    - 包含头部特征（From/Subject）或头部分隔符（\r\n\r\n）
    - 取最大的匹配块
    """
    candidates = [
        x for x in lines
        if isinstance(x, (bytes, bytearray))
        and (b"\r\n\r\n" in x or b"From:" in x or b"from:" in x or b"Subject:" in x)
    ]
    if candidates:
        return bytes(max(candidates, key=len))
    bs = [bytes(x) for x in lines if isinstance(x, (bytes, bytearray))]
    return max(bs, key=len) if bs else b""


def _decode_header_value(value: str | None) -> str:
    """解码邮件头（处理多编码、encoded-word 格式）。"""
    if not value:
        return ""
    parts = decode_header(value)
    out: list[str] = []
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            try:
                out.append(chunk.decode(charset or "utf-8", errors="replace"))
            except (LookupError, UnicodeDecodeError):
                out.append(chunk.decode("utf-8", errors="replace"))
        else:
            out.append(chunk)
    return "".join(out)


def _is_attachment(part: Message) -> bool:
    """判断 MIME 部分是否为附件。"""
    disp = (part.get("Content-Disposition") or "").lower()
    return "attachment" in disp


def _decode_payload(part: Message) -> str:
    """解码 MIME 部分的 payload（处理 Content-Transfer-Encoding）。"""
    raw = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")


def _extract_text(msg: Message) -> str:
    """从邮件中提取纯文本（优先 text/plain，降级 text/html）。"""
    if msg.is_multipart():
        # 优先 text/plain
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not _is_attachment(part):
                return _decode_payload(part)
        # 无 plain 时用 html 转纯文本
        for part in msg.walk():
            if part.get_content_type() == "text/html" and not _is_attachment(part):
                html = _decode_payload(part)
                return BeautifulSoup(html, "html.parser").get_text(separator="\n").strip()
        return ""
    ctype = msg.get_content_type()
    payload = _decode_payload(msg)
    if ctype == "text/html":
        return BeautifulSoup(payload, "html.parser").get_text(separator="\n").strip()
    return payload


def _parse_email(uid: int, msg: Message) -> Email:
    """解析原始邮件为 Email 对象。"""
    raw_from = msg.get("From") or ""
    decoded_from = _decode_header_value(raw_from)
    name, address = parseaddr(decoded_from)
    subject = _decode_header_value(msg.get("Subject"))
    date_hdr = msg.get("Date")
    received_at = None
    if date_hdr:
        try:
            received_at = parsedate_to_datetime(date_hdr)
        except (TypeError, ValueError):
            received_at = None
    if received_at is None:
        # 日期无效或缺失时用当前时间
        received_at = datetime.now(timezone.utc)
    elif received_at.tzinfo is None:
        # RFC 5322 允许无时区日期，默认 UTC 避免与时区感知时间比较报错
        received_at = received_at.replace(tzinfo=timezone.utc)
    body_text = _extract_text(msg)
    return Email(
        uid=uid,
        folder="INBOX",
        from_name=name or address,
        from_address=address,
        subject=subject,
        body_text=body_text,
        received_at=received_at,
    )
