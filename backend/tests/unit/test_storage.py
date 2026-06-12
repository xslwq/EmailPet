"""Tests for emailpet.storage."""
import pytest
from datetime import datetime, timezone
from emailpet.storage.uid_store import UIDStore
from emailpet.storage.archive_log import ArchiveLog
from emailpet.mail.models import Email


@pytest.fixture
def uid_db(tmp_path):
    return UIDStore(tmp_path / "uid.db")


@pytest.fixture
def archive_db(tmp_path):
    return ArchiveLog(tmp_path / "arch.db")


@pytest.fixture
def sample_email():
    return Email(
        uid=42,
        folder="INBOX",
        from_name="Boss",
        from_address="boss@x.com",
        subject="Subject",
        body_text="body",
        received_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
    )


# ------------- UIDStore -------------


def test_uid_store_mark_and_check(uid_db):
    assert uid_db.is_processed(42) is False
    uid_db.mark_processed(42)
    assert uid_db.is_processed(42) is True
    assert uid_db.is_processed(99) is False


def test_uid_store_double_mark_idempotent(uid_db):
    uid_db.mark_processed(42)
    uid_db.mark_processed(42)  # should not raise
    assert uid_db.is_processed(42) is True


def test_uid_store_processed_uids_set(uid_db):
    uid_db.mark_processed(1)
    uid_db.mark_processed(2)
    uid_db.mark_processed(3)
    assert uid_db.processed_uids() == {1, 2, 3}


def test_uid_store_persists_across_instances(tmp_path):
    db = tmp_path / "p.db"
    s1 = UIDStore(db)
    s1.mark_processed(7)
    s1.close()
    s2 = UIDStore(db)
    assert s2.is_processed(7) is True


def test_uid_store_creates_parent_dir(tmp_path):
    nested = tmp_path / "a" / "b" / "c.db"
    UIDStore(nested)  # should not raise
    assert nested.parent.is_dir()


# ------------- ArchiveLog -------------


def test_archive_log_writes_and_reads(archive_db, sample_email):
    archive_db.log(sample_email, "promo")
    rows = archive_db.query_recent()
    assert len(rows) == 1
    r = rows[0]
    assert r["uid"] == 42
    assert r["from_address"] == "boss@x.com"
    assert r["subject"] == "Subject"
    assert r["category"] == "promo"
    assert r["archived_at"]


def test_archive_log_query_recent_ordering(archive_db, sample_email):
    archive_db.log(sample_email, "promo")
    e2 = Email(
        uid=43,
        folder="INBOX",
        from_name="Other",
        from_address="o@x.com",
        subject="Later",
        body_text="b",
        received_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
    )
    archive_db.log(e2, "notification")
    rows = archive_db.query_recent()
    # Most recent first; uid=43 was logged second
    assert rows[0]["uid"] == 43
    assert rows[1]["uid"] == 42


def test_archive_log_query_recent_limit(archive_db, sample_email):
    for i in range(60):
        e = Email(
            uid=i,
            folder="INBOX",
            from_name="x",
            from_address="x@x.com",
            subject="s",
            body_text="b",
            received_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
        )
        archive_db.log(e, "promo")
    rows = archive_db.query_recent(limit=10)
    assert len(rows) == 10


def test_archive_log_persists_across_instances(tmp_path, sample_email):
    db = tmp_path / "a.db"
    log1 = ArchiveLog(db)
    log1.log(sample_email, "promo")
    log1.close()
    log2 = ArchiveLog(db)
    assert len(log2.query_recent()) == 1
