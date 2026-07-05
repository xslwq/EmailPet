"""Tests for profile_update_node."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from emailpet.agent.profile_update import profile_update_node
from emailpet.mail.models import Draft, Email, Summary
from emailpet.storage.user_profile_store import UserProfileStore


@pytest.fixture
def store(tmp_path):
    return UserProfileStore(tmp_path / "profile.db")


@pytest.fixture
def sample_email():
    return Email(
        uid=42, folder="INBOX", from_name="老板", from_address="boss@x.com",
        subject="方案", body_text="请提交方案。",
        received_at=datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def original_draft():
    return Draft(body="此致敬礼", reason="正式")


@pytest.fixture
def modified_feedback():
    return "用'祝好'结尾，不要此致敬礼"


async def test_profile_update_merges_patch(store, sample_email, original_draft, modified_feedback):
    llm = MagicMock()
    llm.extract_profile_patch = AsyncMock(return_value={
        "common_phrases": ["祝好"],
        "honorific": False,
    })
    push_cb = AsyncMock()
    state = {
        "current_email": sample_email,
        "original_draft": original_draft,
        "user_feedback": modified_feedback,
    }
    patch = await profile_update_node(state, llm, store, push_cb)
    assert patch == {"original_draft": None}
    profile = store.get()
    assert "祝好" in profile["common_phrases"]
    assert profile["honorific"] is False


async def test_profile_update_llm_failure_does_not_block(store, sample_email, original_draft, modified_feedback):
    from emailpet.agent.llm import LLMError
    llm = MagicMock()
    llm.extract_profile_patch = AsyncMock(side_effect=LLMError("oops"))
    push_cb = AsyncMock()
    state = {
        "current_email": sample_email,
        "original_draft": original_draft,
        "user_feedback": modified_feedback,
    }
    patch = await profile_update_node(state, llm, store, push_cb)
    assert patch == {"original_draft": None}
    push_cb.assert_awaited()
    event_type, _ = push_cb.await_args.args
    assert event_type == "error"


async def test_profile_update_missing_original_draft_returns_empty(store, sample_email):
    llm = MagicMock()
    push_cb = AsyncMock()
    state = {"current_email": sample_email}
    patch = await profile_update_node(state, llm, store, push_cb)
    assert patch == {}
    llm.extract_profile_patch.assert_not_called()
