"""Tests for EmailsStore."""
from datetime import datetime, timezone

import pytest

from emailpet.mail.models import Email, Summary
from emailpet.storage.emails_store import EmailsStore


@pytest.fixture
def store(tmp_path):
    return EmailsStore(tmp_path / "emails.db")


@pytest.fixture
def sample_email():
    return Email(
        uid=42,
        folder="INBOX",
        from_name="老板",
        from_address="boss@x.com",
        subject="周三方案",
        body_text="请周三前提交方案。",
        received_at=datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_summary():
    return Summary(
        text="老板让交方案",
        is_important=True,
        category="work",
        suggested_action="reply",
        needs_reply=True,
    )


def test_upsert_writes_email_and_summary(store, sample_email, sample_summary):
    store.upsert(sample_email, sample_summary)
    row = store.get_by_uid(42)
    assert row["sender_address"] == "boss@x.com"
    assert row["summary"] == "老板让交方案"
    assert row["is_important"] is True
    assert row["needs_reply"] is True
    assert row["category"] == "work"
    assert row["user_action"] == "pending"
    assert row["indexed_at"] is None


def test_upsert_replaces_existing(store, sample_email, sample_summary):
    store.upsert(sample_email, sample_summary)
    updated_summary = Summary(
        text="更新摘要", is_important=False, category="promo",
        suggested_action="archive", needs_reply=False,
    )
    store.upsert(sample_email, updated_summary)
    row = store.get_by_uid(42)
    assert row["summary"] == "更新摘要"
    assert row["is_important"] is False


def test_update_action_replied(store, sample_email, sample_summary):
    store.upsert(sample_email, sample_summary)
    store.update_action(42, "replied", replied_body="好的，周三前交。")
    row = store.get_by_uid(42)
    assert row["user_action"] == "replied"
    assert row["replied_body"] == "好的，周三前交。"


def test_update_action_archived(store, sample_email, sample_summary):
    store.upsert(sample_email, sample_summary)
    store.update_action(42, "archived")
    row = store.get_by_uid(42)
    assert row["user_action"] == "archived"


def test_mark_indexed(store, sample_email, sample_summary):
    store.upsert(sample_email, sample_summary)
    store.mark_indexed(42)
    row = store.get_by_uid(42)
    assert row["indexed_at"] is not None


def test_query_unindexed(store, sample_email, sample_summary):
    other = Email(
        uid=43, folder="INBOX", from_name="a", from_address="a@x.com",
        subject="s", body_text="b",
        received_at=datetime(2026, 6, 12, 11, 0, tzinfo=timezone.utc),
    )
    other_summary = Summary(
        text="x", is_important=True, category="work",
        suggested_action="reply", needs_reply=True,
    )
    store.upsert(sample_email, sample_summary)
    store.upsert(other, other_summary)
    store.mark_indexed(42)
    unindexed = store.query_unindexed()
    assert [u["uid"] for u in unindexed] == [43]


def test_get_by_sender(store, sample_email, sample_summary):
    store.upsert(sample_email, sample_summary)
    rows = store.get_by_sender("boss@x.com")
    assert len(rows) == 1
    assert rows[0]["uid"] == 42


def test_get_by_uid_not_found(store):
    assert store.get_by_uid(999) is None
