"""Tests for emailpet.mail.smtp_client."""
import base64
import pytest
import smtplib
from unittest.mock import MagicMock, patch
from emailpet.mail.smtp_client import SMTPClient


@pytest.fixture
def mock_smtp_class(monkeypatch):
    """Patch smtplib.SMTP_SSL with a MagicMock factory; return the per-instance mock."""
    instance = MagicMock()
    instance.login = MagicMock()
    instance.sendmail = MagicMock()
    instance.quit = MagicMock()
    cls = MagicMock(return_value=instance)
    monkeypatch.setattr("emailpet.mail.smtp_client.smtplib.SMTP_SSL", cls)
    return cls, instance


async def test_send_success(mock_smtp_class):
    cls, instance = mock_smtp_class
    client = SMTPClient("smtp.example.com", 465, "u@example.com", "p")
    await client.send("to@example.com", "hi", "hello body")
    cls.assert_called_once_with("smtp.example.com", 465, timeout=30)
    instance.login.assert_called_once_with("u@example.com", "p")
    instance.sendmail.assert_called_once()
    args, _ = instance.sendmail.call_args
    assert args[0] == "u@example.com"
    assert args[1] == ["to@example.com"]
    # Body may be raw or base64-encoded (MIMEText with utf-8 base64-encodes by default)
    msg_str = args[2]
    body_b64 = base64.b64encode(b"hello body").decode()
    assert "hello body" in msg_str or body_b64 in msg_str
    instance.quit.assert_called_once()


async def test_send_unicode_subject(mock_smtp_class):
    cls, instance = mock_smtp_class
    client = SMTPClient("smtp.example.com", 465, "u@example.com", "p")
    await client.send("to@example.com", "测试主题", "你好")
    args, _ = instance.sendmail.call_args
    msg_str = args[2]
    # Subject should be RFC 2047 encoded (=?utf-8?...?=)
    assert "=?utf-8?" in msg_str.lower() or "=?UTF-8?" in msg_str
    # Body should be encoded too (typically base64 for utf-8 MIMEText)
    # Just check that the raw bytes "你好" don't appear (they should be encoded)
    # Actually MIMEText with utf-8 base64-encodes by default
    # Less strict assertion: the message must be a valid string that contains utf-8 marker
    assert "utf-8" in msg_str.lower()


async def test_send_auth_failure(mock_smtp_class):
    cls, instance = mock_smtp_class
    instance.login.side_effect = smtplib.SMTPAuthenticationError(535, b"auth failed")
    client = SMTPClient("smtp.example.com", 465, "u@example.com", "wrong")
    with pytest.raises(smtplib.SMTPAuthenticationError):
        await client.send("to@example.com", "hi", "x")


async def test_send_connection_refused(monkeypatch):
    """SMTP_SSL constructor raising OSError propagates."""
    def raise_connect(*a, **kw):
        raise OSError("connection refused")
    monkeypatch.setattr("emailpet.mail.smtp_client.smtplib.SMTP_SSL", raise_connect)
    client = SMTPClient("smtp.example.com", 465, "u", "p")
    with pytest.raises(OSError):
        await client.send("to@example.com", "hi", "x")


async def test_close_no_op(mock_smtp_class):
    """close() is a no-op since each send opens a fresh connection."""
    client = SMTPClient("smtp.example.com", 465, "u", "p")
    await client.close()  # should not raise
