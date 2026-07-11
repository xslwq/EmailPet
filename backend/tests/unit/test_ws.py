"""Tests for emailpet.ws — WebSocket connection management and message dispatch."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from emailpet.ws import ConnectionManager, PENDING_QUEUE_MAX


@pytest.fixture
def manager():
    return ConnectionManager()


@pytest.fixture
def fake_ws():
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


@pytest.fixture
def fake_agent():
    a = MagicMock()
    a.aupdate_state = AsyncMock()
    a.ainvoke = AsyncMock()
    return a


@pytest.fixture
def fake_free_chat_agent():
    a = MagicMock()
    a.aupdate_state = AsyncMock()
    a.ainvoke = AsyncMock()
    return a


# --------- push / buffering ---------


async def test_push_with_connection_sends_immediately(manager, fake_ws):
    await manager.attach(fake_ws)
    await manager.push("summary", {"thread_id": "x", "summary": "y"})
    fake_ws.send_json.assert_awaited_once()
    sent = fake_ws.send_json.await_args.args[0]
    assert sent == {"type": "summary", "thread_id": "x", "summary": "y"}


async def test_push_without_connection_buffers(manager):
    await manager.push("summary", {"summary": "x"})
    # not connected — nothing to send to, message buffered
    # No exception should have been raised
    # internal: queue length 1
    assert len(manager._pending) == 1


async def test_buffer_capped_at_max(manager):
    for i in range(PENDING_QUEUE_MAX + 10):
        await manager.push("agent_say", {"text": str(i)})
    assert len(manager._pending) == PENDING_QUEUE_MAX


async def test_flush_pending_sends_buffered(manager, fake_ws):
    await manager.push("agent_say", {"text": "queued1"})
    await manager.push("agent_say", {"text": "queued2"})
    await manager.attach(fake_ws)
    await manager.flush_pending()
    assert fake_ws.send_json.await_count == 2
    assert len(manager._pending) == 0


async def test_send_failure_buffers_message(manager, fake_ws):
    fake_ws.send_json.side_effect = RuntimeError("ws closed")
    await manager.attach(fake_ws)
    await manager.push("summary", {"x": 1})
    # Should detach and buffer
    assert manager.connected is False
    assert len(manager._pending) == 1


# --------- process_message dispatch ---------


async def test_process_decision_intent_resumes_agent(manager, fake_agent, fake_free_chat_agent):
    await manager.process_message(
        {"type": "decision_intent", "thread_id": "email_42", "intent": "reply"},
        fake_agent,
        fake_free_chat_agent,
    )
    fake_agent.aupdate_state.assert_awaited_once_with(
        {"configurable": {"thread_id": "email_42"}},
        {"current_intent": "reply"},
    )
    fake_agent.ainvoke.assert_awaited_once()


async def test_process_decision_intent_invalid_pushes_error(manager, fake_ws, fake_agent, fake_free_chat_agent):
    await manager.attach(fake_ws)
    await manager.process_message(
        {"type": "decision_intent", "thread_id": "x", "intent": "bogus"},
        fake_agent,
        fake_free_chat_agent,
    )
    # error pushed, agent not called
    fake_agent.aupdate_state.assert_not_awaited()
    args = fake_ws.send_json.await_args.args[0]
    assert args["type"] == "error"


async def test_process_decision_draft_approve(manager, fake_agent, fake_free_chat_agent):
    await manager.process_message(
        {"type": "decision_draft", "thread_id": "email_42", "decision": "approve"},
        fake_agent,
        fake_free_chat_agent,
    )
    fake_agent.aupdate_state.assert_awaited_once_with(
        {"configurable": {"thread_id": "email_42"}},
        {"draft_decision": "approve"},
    )


async def test_process_decision_draft_modify_includes_feedback(manager, fake_agent, fake_free_chat_agent):
    await manager.process_message(
        {
            "type": "decision_draft",
            "thread_id": "email_42",
            "decision": "modify",
            "feedback": "shorter",
        },
        fake_agent,
        fake_free_chat_agent,
    )
    args, _ = fake_agent.aupdate_state.await_args
    assert args[1] == {"draft_decision": "modify", "user_feedback": "shorter"}


async def test_process_user_say_routes_to_free_chat_first_time(manager, fake_ws, fake_agent, fake_free_chat_agent):
    await manager.attach(fake_ws)
    # 首次调用：aupdate_state 抛出异常 → ainvoke 被调用
    fake_free_chat_agent.aupdate_state.side_effect = RuntimeError("thread not found")
    await manager.process_message({"type": "user_say", "text": "hi"}, fake_agent, fake_free_chat_agent)
    fake_free_chat_agent.aupdate_state.assert_awaited_once()
    fake_free_chat_agent.ainvoke.assert_awaited_once()


async def test_process_user_say_routes_to_free_chat_subsequent(manager, fake_ws, fake_agent, fake_free_chat_agent):
    await manager.attach(fake_ws)
    # 后续调用：aupdate_state 成功 → ainvoke(None) 被调用
    await manager.process_message({"type": "user_say", "text": "hi again"}, fake_agent, fake_free_chat_agent)
    fake_free_chat_agent.aupdate_state.assert_awaited_once()
    fake_free_chat_agent.ainvoke.assert_awaited_once_with(None, {"configurable": {"thread_id": "chat_default"}})


async def test_process_user_say_no_free_chat_agent_fallback(manager, fake_ws, fake_agent):
    await manager.attach(fake_ws)
    # free_chat_agent 为 None → 推送提示文本
    await manager.process_message({"type": "user_say", "text": "hi"}, fake_agent, None)
    args = fake_ws.send_json.await_args.args[0]
    assert args["type"] == "agent_say"
    assert "未配置 embedding" in args["text"]


async def test_process_resync_flushes_pending(manager, fake_ws, fake_agent, fake_free_chat_agent):
    await manager.push("summary", {"q": 1})
    await manager.attach(fake_ws)
    await manager.process_message({"type": "resync"}, fake_agent, fake_free_chat_agent)
    assert fake_ws.send_json.await_count == 1
    assert len(manager._pending) == 0


async def test_process_ping_is_noop(manager, fake_ws, fake_agent, fake_free_chat_agent):
    await manager.attach(fake_ws)
    await manager.process_message({"type": "ping"}, fake_agent, fake_free_chat_agent)
    fake_ws.send_json.assert_not_awaited()
    fake_agent.aupdate_state.assert_not_awaited()


async def test_process_unknown_type_logs_no_crash(manager, fake_agent, fake_free_chat_agent):
    # Should not raise
    await manager.process_message({"type": "weird_command"}, fake_agent, fake_free_chat_agent)


# --------- attach/detach ---------


async def test_attach_detach_state(manager, fake_ws):
    assert manager.connected is False
    await manager.attach(fake_ws)
    assert manager.connected is True
    await manager.detach()
    assert manager.connected is False
