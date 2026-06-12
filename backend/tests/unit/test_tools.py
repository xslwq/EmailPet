"""Tests for emailpet.agent.tools."""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from emailpet.agent.tools import AgentTools, _reply_subject
from emailpet.mail.models import Email


@pytest.fixture
def sample_email():
    return Email(
        uid=42,
        folder="INBOX",
        from_name="老板",
        from_address="boss@example.com",
        subject="周三方案",
        body_text="请周三前提交方案。",
        received_at=datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def fake_imap_smtp():
    imap = AsyncMock()
    smtp = AsyncMock()
    return imap, smtp


async def test_reply_success(fake_imap_smtp, sample_email):
    imap, smtp = fake_imap_smtp
    tools = AgentTools(imap, smtp)
    result = await tools.reply(sample_email, "好的，会按时提交")
    assert result == {"status": "sent"}
    smtp.send.assert_awaited_once_with(
        to_addr="boss@example.com",
        subject="Re: 周三方案",
        body="好的，会按时提交",
    )
    imap.mark_read.assert_awaited_once_with(42)


async def test_reply_smtp_failure(fake_imap_smtp, sample_email):
    imap, smtp = fake_imap_smtp
    smtp.send.side_effect = OSError("conn refused")
    tools = AgentTools(imap, smtp)
    result = await tools.reply(sample_email, "x")
    assert result["status"] == "error"
    assert "conn refused" in result["message"]
    # mark_read NOT called when send fails
    imap.mark_read.assert_not_awaited()


async def test_reply_succeeds_even_if_mark_read_fails(fake_imap_smtp, sample_email):
    """Reply was sent — don't fail the whole operation just because mark-read failed."""
    imap, smtp = fake_imap_smtp
    imap.mark_read.side_effect = OSError("imap glitch")
    tools = AgentTools(imap, smtp)
    result = await tools.reply(sample_email, "x")
    assert result == {"status": "sent"}


async def test_archive_success(fake_imap_smtp, sample_email):
    imap, smtp = fake_imap_smtp
    tools = AgentTools(imap, smtp)
    result = await tools.archive(sample_email)
    assert result == {"status": "archived"}
    imap.archive.assert_awaited_once_with(42)


async def test_archive_failure(fake_imap_smtp, sample_email):
    imap, smtp = fake_imap_smtp
    imap.archive.side_effect = RuntimeError("imap broken")
    tools = AgentTools(imap, smtp)
    result = await tools.archive(sample_email)
    assert result["status"] == "error"
    assert "imap broken" in result["message"]


async def test_mark_read_success(fake_imap_smtp, sample_email):
    imap, smtp = fake_imap_smtp
    tools = AgentTools(imap, smtp)
    result = await tools.mark_read(sample_email)
    assert result == {"status": "read"}
    imap.mark_read.assert_awaited_once_with(42)


async def test_mark_read_failure(fake_imap_smtp, sample_email):
    imap, smtp = fake_imap_smtp
    imap.mark_read.side_effect = RuntimeError("oops")
    tools = AgentTools(imap, smtp)
    result = await tools.mark_read(sample_email)
    assert result["status"] == "error"


def test_reply_subject_already_has_re():
    assert _reply_subject("Re: 周三方案") == "Re: 周三方案"
    assert _reply_subject("RE: 周三方案") == "RE: 周三方案"
    assert _reply_subject("re: x") == "re: x"


def test_reply_subject_adds_re():
    assert _reply_subject("周三方案") == "Re: 周三方案"
    assert _reply_subject("  周三方案  ") == "Re: 周三方案"
