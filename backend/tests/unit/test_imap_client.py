"""Tests for emailpet.mail.imap_client."""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from emailpet.mail.imap_client import IMAPClient, IMAPAuthError, IMAPCommandError


# Build a fake RFC822 raw email
SAMPLE_RAW_EMAIL = (
    b"From: =?utf-8?B?5byg5LiJ?= <zhangsan@example.com>\r\n"
    b"To: me@example.com\r\n"
    b"Subject: =?utf-8?B?5rWL6K+V6YKu5Lu2?=\r\n"  # "测试邮件"
    b"Date: Mon, 12 Jun 2026 10:00:00 +0000\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"\r\n"
    b"\xe4\xbd\xa0\xe5\xa5\xbd\xef\xbc\x8c\xe8\xbf\x99\xe6\x98\xaf\xe5\x86\x85\xe5\xae\xb9\xe3\x80\x82"  # 你好，这是内容。
)


def make_fake_aioimap(uid_search_return, uid_fetch_return=None, login_status="OK", select_status="OK"):
    """Return a fake IMAP4_SSL instance."""
    fake = MagicMock()
    fake.wait_hello_from_server = AsyncMock(return_value=None)
    fake.login = AsyncMock(return_value=(login_status, [b"login response"]))
    fake.select = AsyncMock(return_value=(select_status, [b"OK"]))
    fake.uid_search = AsyncMock(return_value=("OK", [uid_search_return, b"Search completed."]))

    async def _uid(command, *args):
        if command == "FETCH":
            return ("OK", [b"1 (UID 1 RFC822 {123}", uid_fetch_return, b")", b"Fetch completed."])
        if command == "STORE":
            return ("OK", [b"Store completed."])
        if command == "COPY":
            return ("OK", [b"Copy completed."])
        return ("OK", [b""])

    fake.uid = AsyncMock(side_effect=_uid)
    fake.expunge = AsyncMock(return_value=("OK", [b""]))
    fake.logout = AsyncMock(return_value=("OK", [b""]))
    return fake


@pytest.fixture
def patch_imap(monkeypatch):
    """Helper: pass in a fake instance, get IMAP4_SSL patched."""
    def _apply(fake):
        cls = MagicMock(return_value=fake)
        monkeypatch.setattr("emailpet.mail.imap_client.aioimaplib.IMAP4_SSL", cls)
        return cls
    return _apply


@pytest.mark.asyncio
async def test_poll_returns_new_emails(patch_imap):
    fake = make_fake_aioimap(uid_search_return=b"42", uid_fetch_return=SAMPLE_RAW_EMAIL)
    patch_imap(fake)
    client = IMAPClient("imap.example.com", 993, "u", "p")
    emails = await client.poll(seen_uids=set())
    assert len(emails) == 1
    e = emails[0]
    assert e.uid == 42
    assert e.from_address == "zhangsan@example.com"
    assert "张三" in e.from_name
    assert "测试邮件" in e.subject
    assert "你好" in e.body_text
    assert isinstance(e.received_at, datetime)


@pytest.mark.asyncio
async def test_poll_uid_dedup(patch_imap):
    fake = make_fake_aioimap(uid_search_return=b"42 43", uid_fetch_return=SAMPLE_RAW_EMAIL)
    patch_imap(fake)
    client = IMAPClient("imap.example.com", 993, "u", "p")
    emails = await client.poll(seen_uids={42})
    # should only fetch UID 43, not 42
    assert len(emails) == 1
    assert emails[0].uid == 43


@pytest.mark.asyncio
async def test_poll_empty(patch_imap):
    fake = make_fake_aioimap(uid_search_return=b"")
    patch_imap(fake)
    client = IMAPClient("imap.example.com", 993, "u", "p")
    emails = await client.poll(seen_uids=set())
    assert emails == []


@pytest.mark.asyncio
async def test_poll_auth_failure(patch_imap):
    fake = make_fake_aioimap(uid_search_return=b"", login_status="NO")
    patch_imap(fake)
    client = IMAPClient("imap.example.com", 993, "u", "wrong")
    with pytest.raises(IMAPAuthError):
        await client.poll(seen_uids=set())


@pytest.mark.asyncio
async def test_archive_with_archive_folder(patch_imap):
    fake = make_fake_aioimap(uid_search_return=b"")
    patch_imap(fake)
    client = IMAPClient("imap.example.com", 993, "u", "p")
    await client.connect()
    await client.archive(42)
    # Verify COPY then STORE+\Deleted then EXPUNGE were called
    calls = [c.args for c in fake.uid.await_args_list]
    assert ("COPY", "42", "Archive") in calls
    assert any(c[0] == "STORE" and c[1] == "42" and "\\Deleted" in c[2] for c in calls)
    fake.expunge.assert_awaited()


@pytest.mark.asyncio
async def test_archive_fallback_no_archive_folder(patch_imap):
    """When COPY fails (no Archive folder), fallback to just marking \\Seen."""
    fake = make_fake_aioimap(uid_search_return=b"")
    patch_imap(fake)

    async def uid_side_effect(command, *args):
        if command == "COPY":
            return ("NO", [b"No such folder"])
        if command == "STORE":
            return ("OK", [b""])
        return ("OK", [b""])

    fake.uid = AsyncMock(side_effect=uid_side_effect)
    client = IMAPClient("imap.example.com", 993, "u", "p")
    await client.connect()
    await client.archive(42)
    calls = [c.args for c in fake.uid.await_args_list]
    # COPY was tried
    assert ("COPY", "42", "Archive") in calls
    # STORE +Seen was called (fallback) — and STORE +Deleted was NOT
    assert any(c[0] == "STORE" and "\\Seen" in c[2] for c in calls)
    assert not any(c[0] == "STORE" and "\\Deleted" in c[2] for c in calls)


@pytest.mark.asyncio
async def test_mark_read(patch_imap):
    fake = make_fake_aioimap(uid_search_return=b"")
    patch_imap(fake)
    client = IMAPClient("imap.example.com", 993, "u", "p")
    await client.connect()
    await client.mark_read(42)
    calls = [c.args for c in fake.uid.await_args_list]
    assert any(c[0] == "STORE" and c[1] == "42" and "\\Seen" in c[2] for c in calls)
