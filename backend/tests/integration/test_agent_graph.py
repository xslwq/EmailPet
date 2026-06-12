"""Integration tests for the LangGraph agent — exercises full graph paths."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from emailpet.agent.graph import build_workflow
from emailpet.mail.models import Draft, Email, Summary


@pytest.fixture
def sample_email():
    return Email(
        uid=42,
        folder="INBOX",
        from_name="Boss",
        from_address="boss@x.com",
        subject="Plan",
        body_text="Submit by Wed",
        received_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
    )


@pytest.fixture
def push_cb():
    return AsyncMock()


def make_agent(llm, tools, archive_log, push_cb):
    """Build a workflow and compile with an in-memory checkpointer for tests."""
    workflow = build_workflow(llm, tools, archive_log, push_cb)
    return workflow.compile(
        checkpointer=InMemorySaver(),
        interrupt_before=["wait_intent", "wait_decision"],
    )


async def test_silent_archive_path(sample_email, push_cb):
    """Unimportant email → silent_archive → END, no user-facing push."""
    llm = MagicMock()
    llm.summarize = AsyncMock(
        return_value=Summary(
            text="ad", is_important=False, category="promo", suggested_action="archive"
        )
    )
    tools = MagicMock()
    tools.archive = AsyncMock(return_value={"status": "archived"})
    archive_log = MagicMock()

    agent = make_agent(llm, tools, archive_log, push_cb)
    config = {"configurable": {"thread_id": "email_42"}}
    await agent.ainvoke({"pending_emails": [sample_email]}, config)

    tools.archive.assert_awaited_once()
    archive_log.log.assert_called_once()
    push_cb.assert_not_awaited()

    snap = await agent.aget_state(config)
    assert snap.next == ()


async def test_important_path_pauses_at_interrupt(sample_email, push_cb):
    """Important email → notify_summary pushed → graph interrupts before wait_intent."""
    llm = MagicMock()
    llm.summarize = AsyncMock(
        return_value=Summary(
            text="boss says hi",
            is_important=True,
            category="work",
            suggested_action="reply",
        )
    )
    tools = MagicMock()
    archive_log = MagicMock()

    agent = make_agent(llm, tools, archive_log, push_cb)
    config = {"configurable": {"thread_id": "email_42"}}
    await agent.ainvoke({"pending_emails": [sample_email]}, config)

    push_calls = [c.args[0] for c in push_cb.await_args_list]
    assert "summary" in push_calls

    snap = await agent.aget_state(config)
    assert "wait_intent" in snap.next


async def test_summarize_consumes_pending_email(sample_email, push_cb):
    """summarize_node should pop the head of pending_emails."""
    llm = MagicMock()
    llm.summarize = AsyncMock(
        return_value=Summary(
            text="x", is_important=False, category="promo", suggested_action="archive"
        )
    )
    tools = MagicMock()
    tools.archive = AsyncMock(return_value={"status": "archived"})
    archive_log = MagicMock()

    agent = make_agent(llm, tools, archive_log, push_cb)
    config = {"configurable": {"thread_id": "email_42"}}
    final = await agent.ainvoke({"pending_emails": [sample_email]}, config)
    assert final["pending_emails"] == []
    assert final["current_email"] == sample_email


async def test_intent_archive_path(sample_email, push_cb):
    """Important email, user picks archive → execute_archive → END."""
    llm = MagicMock()
    llm.summarize = AsyncMock(
        return_value=Summary(
            text="x", is_important=True, category="work", suggested_action="archive"
        )
    )
    tools = MagicMock()
    tools.archive = AsyncMock(return_value={"status": "archived"})
    archive_log = MagicMock()

    agent = make_agent(llm, tools, archive_log, push_cb)
    config = {"configurable": {"thread_id": "email_42"}}
    await agent.ainvoke({"pending_emails": [sample_email]}, config)

    await agent.aupdate_state(config, {"current_intent": "archive"})
    await agent.ainvoke(None, config)

    tools.archive.assert_awaited_once()
    snap = await agent.aget_state(config)
    assert snap.next == ()


async def test_full_reply_flow(sample_email, push_cb):
    """summarize → notify → wait_intent(reply) → draft_reply → wait_decision(approve) → execute_reply → END."""
    llm = MagicMock()
    llm.summarize = AsyncMock(
        return_value=Summary(
            text="x", is_important=True, category="work", suggested_action="reply"
        )
    )
    llm.draft_reply = AsyncMock(return_value=Draft(body="OK", reason="ack"))
    tools = MagicMock()
    tools.reply = AsyncMock(return_value={"status": "sent"})
    archive_log = MagicMock()

    agent = make_agent(llm, tools, archive_log, push_cb)
    config = {"configurable": {"thread_id": "email_42"}}

    # First run: until first interrupt (before wait_intent)
    await agent.ainvoke({"pending_emails": [sample_email]}, config)
    snap = await agent.aget_state(config)
    assert "wait_intent" in snap.next

    # User picks reply
    await agent.aupdate_state(config, {"current_intent": "reply"})
    await agent.ainvoke(None, config)
    snap = await agent.aget_state(config)
    assert "wait_decision" in snap.next

    # User approves
    await agent.aupdate_state(config, {"draft_decision": "approve"})
    await agent.ainvoke(None, config)

    tools.reply.assert_awaited_once()
    sent_calls = [c for c in push_cb.await_args_list if c.args[0] == "sent"]
    assert len(sent_calls) == 1


async def test_modify_loop(sample_email, push_cb):
    """User modifies draft twice, then approves — draft_reply runs 3 times."""
    llm = MagicMock()
    llm.summarize = AsyncMock(
        return_value=Summary(
            text="x", is_important=True, category="work", suggested_action="reply"
        )
    )
    llm.draft_reply = AsyncMock(
        side_effect=[
            Draft(body="v1", reason="r1"),
            Draft(body="v2", reason="r2"),
            Draft(body="v3", reason="r3"),
        ]
    )
    tools = MagicMock()
    tools.reply = AsyncMock(return_value={"status": "sent"})
    archive_log = MagicMock()

    agent = make_agent(llm, tools, archive_log, push_cb)
    config = {"configurable": {"thread_id": "email_42"}}

    await agent.ainvoke({"pending_emails": [sample_email]}, config)
    await agent.aupdate_state(config, {"current_intent": "reply"})
    await agent.ainvoke(None, config)  # → wait_decision (after v1)

    # First modify
    await agent.aupdate_state(
        config, {"draft_decision": "modify", "user_feedback": "shorter"}
    )
    await agent.ainvoke(None, config)  # draft_reply v2 → wait_decision

    # Second modify
    await agent.aupdate_state(
        config, {"draft_decision": "modify", "user_feedback": "more polite"}
    )
    await agent.ainvoke(None, config)  # draft_reply v3 → wait_decision

    # Approve
    await agent.aupdate_state(config, {"draft_decision": "approve"})
    await agent.ainvoke(None, config)

    assert llm.draft_reply.await_count == 3
    sent_args = tools.reply.await_args
    # tools.reply(email, body) — body is positional arg index 1
    assert sent_args.args[1] == "v3"
