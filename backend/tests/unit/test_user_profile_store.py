"""Tests for UserProfileStore."""
import pytest

from emailpet.storage.user_profile_store import UserProfileStore


@pytest.fixture
def store(tmp_path):
    return UserProfileStore(tmp_path / "profile.db")


def test_get_returns_empty_profile_on_init(store):
    profile = store.get()
    assert profile["display_name"] is None
    assert profile["common_phrases"] == []
    assert profile["updated_at"] is not None


def test_merge_scalar_fields_overwrite(store):
    store.merge({"display_name": "小王", "tone": "casual", "honorific": False})
    profile = store.get()
    assert profile["display_name"] == "小王"
    assert profile["tone"] == "casual"
    assert profile["honorific"] is False


def test_merge_null_patch_value_skipped(store):
    store.merge({"display_name": "小王"})
    store.merge({"display_name": None, "tone": "formal"})
    profile = store.get()
    assert profile["display_name"] == "小王"
    assert profile["tone"] == "formal"


def test_merge_common_phrases_dedup_union(store):
    store.merge({"common_phrases": ["祝好", "收到"]})
    store.merge({"common_phrases": ["收到", "周末愉快"]})
    profile = store.get()
    assert set(profile["common_phrases"]) == {"收到", "周末愉快", "祝好"}


def test_merge_updates_timestamp(store):
    store.merge({"display_name": "小王"})
    ts1 = store.get()["updated_at"]
    store.merge({"tone": "casual"})
    ts2 = store.get()["updated_at"]
    assert ts2 >= ts1


def test_merge_partial_patch_keeps_other_fields(store):
    store.merge({"display_name": "小王", "tone": "casual"})
    store.merge({"signature": "祝好"})
    profile = store.get()
    assert profile["display_name"] == "小王"
    assert profile["tone"] == "casual"
    assert profile["signature"] == "祝好"
