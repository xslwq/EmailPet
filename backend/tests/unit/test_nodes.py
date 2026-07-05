"""Tests for emailpet.agent.nodes — node functions + routers."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.graph import END

from emailpet.agent.llm import LLMError
from emailpet.agent.nodes import (
    draft_reply_node,
    execute_archive,
    execute_reply,
    is_important_condition,
    notify_reject_node,
    notify_skip_node,
    notify_summary_node,
    route_decision,
    route_intent,
    silent_archive_node,
    summarize_node,
    wait_intent_node,
)
from emailpet.mail.models import Draft, Email, Summary


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
def important_summary():
    return Summary(
        text="老板让交方案", is_important=True, category="work", suggested_action="reply", needs_reply=True
    )


@pytest.fixture
def unimportant_summary():
    return Summary(
        text="广告", is_important=False, category="promo", suggested_action="archive", needs_reply=False
    )


@pytest.fixture
def push_cb():
    return AsyncMock()


# ---------------- summarize_node ----------------


async def test_summarize_node_populates_state(sample_email, push_cb, important_summary):
    llm = MagicMock()
    llm.summarize = AsyncMock(return_value=important_summary)
    state = {"pending_emails": [sample_email]}
    patch = await summarize_node(state, llm, push_cb)
    assert patch["current_email"] == sample_email
    assert patch["current_summary"] == important_summary
    assert patch["pending_emails"] == []
    llm.summarize.assert_awaited_once_with(sample_email.body_text)


async def test_summarize_node_pops_only_first(sample_email, push_cb, important_summary):
    other = Email(
        uid=43,
        folder="INBOX",
        from_name="b",
        from_address="b@x.com",
        subject="s",
        body_text="b",
        received_at=datetime(2026, 6, 12, 11, 0, tzinfo=timezone.utc),
    )
    llm = MagicMock()
    llm.summarize = AsyncMock(return_value=important_summary)
    state = {"pending_emails": [sample_email, other]}
    patch = await summarize_node(state, llm, push_cb)
    assert patch["current_email"] == sample_email
    assert patch["pending_emails"] == [other]


async def test_summarize_node_empty_pending_returns_empty(push_cb):
    llm = MagicMock()
    state = {"pending_emails": []}
    patch = await summarize_node(state, llm, push_cb)
    assert patch == {}


# ---------------- silent_archive_node ----------------


async def test_silent_archive_node_calls_tools_and_log(sample_email, unimportant_summary):
    tools = MagicMock()
    tools.archive = AsyncMock(return_value={"status": "archived"})
    archive_log = MagicMock()
    state = {"current_email": sample_email, "current_summary": unimportant_summary}
    patch = await silent_archive_node(state, tools, archive_log)
    assert patch == {}
    tools.archive.assert_awaited_once_with(sample_email)
    archive_log.log.assert_called_once_with(sample_email, "promo")


async def test_silent_archive_node_log_exception_does_not_raise(sample_email, unimportant_summary):
    tools = MagicMock()
    tools.archive = AsyncMock(return_value={"status": "archived"})
    archive_log = MagicMock()
    archive_log.log.side_effect = RuntimeError("disk full")
    state = {"current_email": sample_email, "current_summary": unimportant_summary}
    # should not raise
    patch = await silent_archive_node(state, tools, archive_log)
    assert patch == {}


# ---------------- notify_summary_node ----------------


async def test_notify_summary_pushes_payload(sample_email, important_summary, push_cb):
    state = {"current_email": sample_email, "current_summary": important_summary}
    patch = await notify_summary_node(state, push_cb, thread_id="email_42")
    assert patch == {}
    push_cb.assert_awaited_once()
    args, _ = push_cb.await_args
    event_type, payload = args
    assert event_type == "summary"
    assert payload["thread_id"] == "email_42"
    assert payload["email"]["from_name"] == "老板"
    assert payload["email"]["from_address"] == "boss@x.com"
    assert payload["body_text"] == sample_email.body_text
    assert payload["summary"] == important_summary.text
    assert payload["suggested_action"] == "reply"


# ---------------- wait_intent_node ----------------


def test_wait_intent_node_passes_through():
    assert wait_intent_node({"foo": "bar"}) == {}


# ---------------- draft_reply_node ----------------


async def test_draft_reply_pushes_and_stores(sample_email, push_cb):
    llm = MagicMock()
    llm.draft_reply = AsyncMock(return_value=Draft(body="好的", reason="确认"))
    state = {"current_email": sample_email, "user_feedback": None}
    patch = await draft_reply_node(state, llm, push_cb, thread_id="email_42")
    assert patch["current_draft"].body == "好的"
    assert patch["original_draft"].body == "好的"
    assert patch["user_feedback"] is None  # cleared
    push_cb.assert_awaited_once()
    event_type, payload = push_cb.await_args.args
    assert event_type == "draft"
    assert payload["draft"] == "好的"


async def test_draft_reply_with_feedback_passes_to_llm(sample_email, push_cb):
    llm = MagicMock()
    llm.draft_reply = AsyncMock(return_value=Draft(body="x", reason="y"))
    state = {"current_email": sample_email, "user_feedback": "客气一点"}
    await draft_reply_node(state, llm, push_cb)
    llm.draft_reply.assert_awaited_once_with(sample_email.body_text, feedback="客气一点", profile_block="")


async def test_draft_reply_llm_error_short_circuits(sample_email, push_cb):
    llm = MagicMock()
    llm.draft_reply = AsyncMock(side_effect=LLMError("oops"))
    state = {"current_email": sample_email}
    patch = await draft_reply_node(state, llm, push_cb)
    assert patch["draft_decision"] == "reject"
    event_type, _ = push_cb.await_args.args
    assert event_type == "error"


async def test_draft_reply_injects_profile(sample_email, push_cb, tmp_path):
    from emailpet.storage.user_profile_store import UserProfileStore
    store = UserProfileStore(tmp_path / "profile.db")
    store.merge({"display_name": "小王", "tone": "casual", "common_phrases": ["祝好"]})
    llm = MagicMock()
    llm.draft_reply = AsyncMock(return_value=Draft(body="好的", reason="ok"))
    llm.extract_profile_patch = AsyncMock(return_value={})
    state = {"current_email": sample_email, "user_feedback": None}
    await draft_reply_node(state, llm, push_cb, profile_store=store)
    args, kwargs = llm.draft_reply.call_args
    # 验证 profile 被拼进 prompt（第 3 个位置参数或 keyword）
    profile_block = kwargs.get("profile_block") or (args[2] if len(args) > 2 else "")
    assert "小王" in profile_block
    assert "casual" in profile_block
    assert "祝好" in profile_block


# ---------------- execute_reply ----------------


async def test_execute_reply_success(sample_email, push_cb):
    tools = MagicMock()
    tools.reply = AsyncMock(return_value={"status": "sent"})
    draft = Draft(body="好的", reason="ok")
    state = {"current_email": sample_email, "current_draft": draft}
    patch = await execute_reply(state, tools, push_cb)
    tools.reply.assert_awaited_once_with(sample_email, "好的")
    assert patch["current_draft"] is None
    event_type, _ = push_cb.await_args.args
    assert event_type == "sent"


async def test_execute_reply_failure_pushes_error(sample_email, push_cb):
    tools = MagicMock()
    tools.reply = AsyncMock(return_value={"status": "error", "message": "smtp dead"})
    draft = Draft(body="x", reason="y")
    state = {"current_email": sample_email, "current_draft": draft}
    await execute_reply(state, tools, push_cb)
    event_type, payload = push_cb.await_args.args
    assert event_type == "error"
    assert "smtp dead" in payload["message"]


# ---------------- execute_archive ----------------


async def test_execute_archive_calls_tool(sample_email, push_cb):
    tools = MagicMock()
    tools.archive = AsyncMock(return_value={"status": "archived"})
    state = {"current_email": sample_email}
    await execute_archive(state, tools, push_cb)
    tools.archive.assert_awaited_once_with(sample_email)
    # success path now pushes a confirmation agent_say
    event_type, payload = push_cb.await_args.args
    assert event_type == "agent_say"
    assert "归档" in payload["text"]


async def test_execute_archive_failure_pushes_error(sample_email, push_cb):
    tools = MagicMock()
    tools.archive = AsyncMock(return_value={"status": "error", "message": "imap died"})
    state = {"current_email": sample_email}
    await execute_archive(state, tools, push_cb)
    event_type, payload = push_cb.await_args.args
    assert event_type == "error"
    assert "imap died" in payload["message"]


# ---------------- notify_skip / notify_reject ----------------


async def test_notify_skip_pushes_acknowledgement(push_cb):
    await notify_skip_node({}, push_cb)
    event_type, payload = push_cb.await_args.args
    assert event_type == "agent_say"
    assert payload["text"]


async def test_notify_reject_pushes_acknowledgement(push_cb):
    await notify_reject_node({}, push_cb)
    event_type, payload = push_cb.await_args.args
    assert event_type == "agent_say"
    assert payload["text"]


# ---------------- routers ----------------


def test_is_important_condition_true(important_summary):
    assert is_important_condition({"current_summary": important_summary}) == "notify_summary"


def test_is_important_condition_false(unimportant_summary):
    assert is_important_condition({"current_summary": unimportant_summary}) == "silent_archive"


def test_is_important_condition_missing_summary():
    assert is_important_condition({}) == "silent_archive"


def test_route_intent_reply():
    assert route_intent({"current_intent": "reply"}) == "draft_reply"


def test_route_intent_archive():
    assert route_intent({"current_intent": "archive"}) == "execute_archive"


def test_route_intent_skip_routes_to_notify():
    assert route_intent({"current_intent": "skip"}) == "notify_skip"


def test_route_intent_unset_routes_to_notify():
    assert route_intent({}) == "notify_skip"


def test_route_decision_approve():
    assert route_decision({"draft_decision": "approve"}) == "execute_reply"


def test_route_decision_modify():
    assert route_decision({"draft_decision": "modify"}) == "profile_update"


def test_route_decision_reject_routes_to_notify():
    assert route_decision({"draft_decision": "reject"}) == "notify_reject"


def test_route_decision_unset_routes_to_notify():
    assert route_decision({}) == "notify_reject"


# ---------------- Task 8: summarize writes emails_store, notify builds index ----------------


async def test_summarize_node_writes_emails_store(sample_email, important_summary, push_cb, tmp_path):
    from emailpet.storage.emails_store import EmailsStore
    store = EmailsStore(tmp_path / "emails.db")
    llm = MagicMock()
    llm.summarize = AsyncMock(return_value=important_summary)
    state = {"pending_emails": [sample_email]}
    await summarize_node(state, llm, push_cb, emails_store=store)
    row = store.get_by_uid(42)
    assert row is not None
    assert row["summary"] == "老板让交方案"
    assert row["is_important"] is True
    assert row["needs_reply"] is True


async def test_notify_summary_builds_vector_index(sample_email, important_summary, push_cb, tmp_path):
    from emailpet.storage.emails_store import EmailsStore
    from emailpet.storage.email_vec_store import EmailVecStore
    store = EmailsStore(tmp_path / "emails.db")
    store.upsert(sample_email, important_summary)
    vec_store = EmailVecStore(tmp_path / "vec.db", dimensions=4)
    embedding_client = MagicMock()
    embedding_client.embed = AsyncMock(return_value=[0.1, 0.2, 0.3, 0.4])
    state = {"current_email": sample_email, "current_summary": important_summary}
    await notify_summary_node(state, push_cb, emails_store=store, email_vec_store=vec_store, embedding_client=embedding_client)
    results = vec_store.query([0.1, 0.2, 0.3, 0.4], k=1)
    assert results == [42]
    row = store.get_by_uid(42)
    assert row["indexed_at"] is not None
    push_cb.assert_awaited()


async def test_notify_summary_embedding_failure_does_not_block(sample_email, important_summary, push_cb, tmp_path):
    from emailpet.agent.embedding import EmbeddingError
    from emailpet.storage.emails_store import EmailsStore
    from emailpet.storage.email_vec_store import EmailVecStore
    store = EmailsStore(tmp_path / "emails.db")
    store.upsert(sample_email, important_summary)
    vec_store = EmailVecStore(tmp_path / "vec.db", dimensions=4)
    embedding_client = MagicMock()
    embedding_client.embed = AsyncMock(side_effect=EmbeddingError("api dead"))
    state = {"current_email": sample_email, "current_summary": important_summary}
    await notify_summary_node(state, push_cb, emails_store=store, email_vec_store=vec_store, embedding_client=embedding_client)
    push_cb.assert_awaited()
    row = store.get_by_uid(42)
    assert row["indexed_at"] is None


# ---------------- Task 9: 行为回填 execute_reply/archive/skip 写 emails.user_action ----------------


async def test_execute_reply_updates_action(sample_email, important_summary, push_cb, tmp_path):
    from emailpet.storage.emails_store import EmailsStore
    store = EmailsStore(tmp_path / "emails.db")
    store.upsert(sample_email, important_summary)
    tools = MagicMock()
    tools.reply = AsyncMock(return_value={"status": "sent"})
    draft = Draft(body="好的", reason="ok")
    state = {"current_email": sample_email, "current_draft": draft}
    await execute_reply(state, tools, push_cb, emails_store=store)
    row = store.get_by_uid(42)
    assert row["user_action"] == "replied"
    assert row["replied_body"] == "好的"


async def test_execute_archive_updates_action(sample_email, important_summary, push_cb, tmp_path):
    from emailpet.storage.emails_store import EmailsStore
    store = EmailsStore(tmp_path / "emails.db")
    store.upsert(sample_email, important_summary)
    tools = MagicMock()
    tools.archive = AsyncMock(return_value={"status": "archived"})
    state = {"current_email": sample_email}
    await execute_archive(state, tools, push_cb, emails_store=store)
    row = store.get_by_uid(42)
    assert row["user_action"] == "archived"


async def test_silent_archive_updates_action(sample_email, unimportant_summary, tmp_path):
    from emailpet.storage.emails_store import EmailsStore
    store = EmailsStore(tmp_path / "emails.db")
    store.upsert(sample_email, unimportant_summary)
    tools = MagicMock()
    tools.archive = AsyncMock(return_value={"status": "archived"})
    archive_log = MagicMock()
    state = {"current_email": sample_email, "current_summary": unimportant_summary}
    await silent_archive_node(state, tools, archive_log, emails_store=store)
    row = store.get_by_uid(42)
    assert row["user_action"] == "archived"


async def test_notify_skip_updates_action(sample_email, important_summary, push_cb, tmp_path):
    from emailpet.storage.emails_store import EmailsStore
    store = EmailsStore(tmp_path / "emails.db")
    store.upsert(sample_email, important_summary)
    state = {"current_email": sample_email}
    await notify_skip_node(state, push_cb, emails_store=store)
    row = store.get_by_uid(42)
    assert row["user_action"] == "skipped"
