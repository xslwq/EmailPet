"""Async IMAP client wrapper around aioimaplib.

See docs/modules/backend/emailpet/mail/imap_client.md for full module doc.
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
    """IMAP authentication failed."""


class IMAPCommandError(Exception):
    """An IMAP command returned a non-OK response."""

    def __init__(self, command: str, response: object) -> None:
        super().__init__(f"IMAP {command} failed: {response!r}")
        self.command = command
        self.response = response


class IMAPClient:
    def __init__(self, host: str, port: int, username: str, password: str) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self._client: Optional[aioimaplib.IMAP4_SSL] = None

    async def connect(self) -> None:
        if self._client is not None:
            return
        client = aioimaplib.IMAP4_SSL(host=self.host, port=self.port, timeout=30)
        await client.wait_hello_from_server()
        status, _ = await client.login(self.username, self.password)
        if status != "OK":
            raise IMAPAuthError(f"login failed for {self.username}")
        self._client = client

    async def close(self) -> None:
        if self._client is None:
            return
        try:
            await self._client.logout()
        except Exception:
            logger.warning("imap logout failed", exc_info=True)
        self._client = None

    async def poll(self, seen_uids: set[int]) -> tuple[list[Email], list[int]]:
        """Fetch new UNSEEN emails not in ``seen_uids``.

        Returns ``(parsed_emails, processed_uids)``. ``processed_uids`` contains
        both successfully parsed UIDs *and* UIDs whose fetch/parse failed —
        callers are expected to mark all of them as seen so we don't re-fetch
        broken UIDs forever.
        """
        await self.connect()
        assert self._client is not None
        status, _ = await self._client.select("INBOX")
        if status != "OK":
            raise IMAPCommandError("SELECT", status)
        status, lines = await self._client.uid_search("UNSEEN")
        if status != "OK":
            raise IMAPCommandError("UID SEARCH", lines)
        # lines[0] is e.g. b"1 2 3" or b""
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
                # Still mark as processed so caller doesn't re-attempt forever.
                processed.append(uid)
        return out, processed

    async def _fetch_one(self, uid: int) -> Email:
        assert self._client is not None
        status, lines = await self._client.uid("FETCH", str(uid), "(RFC822)")
        if status != "OK":
            raise IMAPCommandError("UID FETCH", lines)
        raw = _extract_raw(lines)
        msg = BytesParser().parsebytes(raw)
        return _parse_email(uid, msg)

    async def archive(self, uid: int) -> None:
        await self.connect()
        assert self._client is not None
        status, _ = await self._client.uid("COPY", str(uid), "Archive")
        if status == "OK":
            store_status, store_resp = await self._client.uid(
                "STORE", str(uid), "+FLAGS (\\Deleted)"
            )
            if store_status != "OK":
                # COPY already duplicated the message; surface the failure
                # rather than silently leaving a duplicate in INBOX.
                raise IMAPCommandError("UID STORE", store_resp)
            expunge_status, expunge_resp = await self._client.expunge()
            if expunge_status != "OK":
                raise IMAPCommandError("EXPUNGE", expunge_resp)
        else:
            logger.info("archive folder unavailable, fallback to mark_read for uid=%s", uid)
            await self._client.uid("STORE", str(uid), "+FLAGS (\\Seen)")

    async def mark_read(self, uid: int) -> None:
        await self.connect()
        assert self._client is not None
        await self._client.uid("STORE", str(uid), "+FLAGS (\\Seen)")


def _extract_raw(lines: list) -> bytes:
    """aioimaplib FETCH returns mixed framing + content lines.

    Find the bytes chunk that's the raw email — heuristic: contains headers
    (Date/From/Subject) or a header/body separator (\\r\\n\\r\\n). Pick the largest
    matching candidate. Falls back to the largest bytes blob.
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
    disp = (part.get("Content-Disposition") or "").lower()
    return "attachment" in disp


def _decode_payload(part: Message) -> str:
    raw = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")


def _extract_text(msg: Message) -> str:
    if msg.is_multipart():
        # prefer text/plain
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not _is_attachment(part):
                return _decode_payload(part)
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
        received_at = datetime.now(timezone.utc)
    elif received_at.tzinfo is None:
        # RFC 5322 allows dates without timezone offset; assume UTC so downstream
        # comparisons against tz-aware datetimes don't blow up.
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
