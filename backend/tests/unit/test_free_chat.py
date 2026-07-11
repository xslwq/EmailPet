"""Tests for free_chat graph backend."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph

from emailpet.agent.free_chat_state import FreeChatState
from emailpet.agent.free_chat_nodes import retrieve_node, llm_reply_node, wait_user_node
from emailpet.agent.free_chat_graph import build_free_chat_workflow
from emailpet.agent.embedding import EmbeddingError


@pytest.fixture
def mock_embedding_client():
    """Fixture for mock EmbeddingClient."""
    client = MagicMock()
    client.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])
    return client


@pytest.fixture
def mock_email_vec_store():
    """Fixture for mock EmailVecStore."""
    store = MagicMock()
    store.query = MagicMock(return_value=[42, 43, 44])
    return store


@pytest.fixture
def mock_emails_store():
    """Fixture for mock EmailsStore."""
    store = MagicMock()
    store.get_by_uid = MagicMock(side_effect=lambda uid: {
        42: {"sender_name": "张三", "subject": "周三会议", "summary": "老板让你开会", "received_at": "2026-07-10", "user_action": "replied"},
        43: {"sender_name": "李四", "subject": "周五聚餐", "summary": "部门聚餐", "received_at": "2026-07-11", "user_action": "pending"},
    }.get(uid))
    return store


@pytest.fixture
def mock_user_profile_store():
    """Fixture for mock UserProfileStore."""
    store = MagicMock()
    store.get = MagicMock(return_value={"display_name": "小王", "tone": "casual"})
    return store


@pytest.fixture
def mock_llm():
    """Fixture for mock LLMClient."""
    llm = MagicMock()
    llm.model = "test-model"
    choice = MagicMock()
    choice.message = MagicMock()
    choice.message.content = "根据邮件，上次会议是周三下午。"
    comp = MagicMock()
    comp.choices = [choice]
    llm.client = MagicMock()
    llm.client.chat = MagicMock()
    llm.client.chat.completions = MagicMock()
    llm.client.chat.completions.create = AsyncMock(return_value=comp)
    return llm


@pytest.fixture
def mock_push_callback():
    """Fixture for mock push_callback."""
    return AsyncMock()


async def test_retrieve_node_returns_uids(mock_embedding_client, mock_email_vec_store, mock_emails_store):
    """Test retrieve_node returns uids from email_vec_store."""
    state: FreeChatState = {
        "messages": [{"role": "user", "content": "上次会议是啥时候？"}]
    }

    result = await retrieve_node(
        state,
        embedding_client=mock_embedding_client,
        email_vec_store=mock_email_vec_store,
        emails_store=mock_emails_store,
    )

    assert "retrieved_emails" in result
    assert result["retrieved_emails"] == [42, 43, 44]
    mock_embedding_client.embed.assert_awaited_once_with("上次会议是啥时候？")
    mock_email_vec_store.query.assert_called_once_with([0.1, 0.2, 0.3], k=5)


async def test_retrieve_node_embedding_failure_returns_empty(mock_embedding_client, mock_email_vec_store, mock_emails_store):
    """Test retrieve_node returns empty list when embedding fails."""
    mock_embedding_client.embed.side_effect = EmbeddingError("API down")

    state: FreeChatState = {
        "messages": [{"role": "user", "content": "上次会议是啥时候？"}]
    }

    result = await retrieve_node(
        state,
        embedding_client=mock_embedding_client,
        email_vec_store=mock_email_vec_store,
        emails_store=mock_emails_store,
    )

    assert "retrieved_emails" in result
    assert result["retrieved_emails"] == []


async def test_retrieve_node_no_user_message_returns_empty(mock_embedding_client, mock_email_vec_store, mock_emails_store):
    """Test retrieve_node returns empty list when no user message."""
    state: FreeChatState = {
        "messages": [{"role": "assistant", "content": "你好！"}]
    }

    result = await retrieve_node(
        state,
        embedding_client=mock_embedding_client,
        email_vec_store=mock_email_vec_store,
        emails_store=mock_emails_store,
    )

    assert result["retrieved_emails"] == []
    mock_embedding_client.embed.assert_not_awaited()


async def test_llm_reply_node_appends_assistant_message(mock_llm, mock_emails_store, mock_user_profile_store, mock_push_callback):
    """Test llm_reply_node appends assistant message and pushes chat_reply."""
    state: FreeChatState = {
        "messages": [{"role": "user", "content": "上次会议是啥时候？"}],
        "retrieved_emails": [42, 43],
    }

    result = await llm_reply_node(
        state,
        llm=mock_llm,
        emails_store=mock_emails_store,
        user_profile_store=mock_user_profile_store,
        push_callback=mock_push_callback,
    )

    assert "messages" in result
    assert len(result["messages"]) == 1
    assert result["messages"][0]["role"] == "assistant"
    assert result["messages"][0]["content"] == "根据邮件，上次会议是周三下午。"

    # Verify push_callback called with chat_reply
    mock_push_callback.assert_awaited_once_with("chat_reply", {
        "thread_id": "chat_default",
        "reply": "根据邮件，上次会议是周三下午。",
        "retrieved": True,
        "retrieved_count": 2,
    })

    # Verify LLM called
    mock_llm.client.chat.completions.create.assert_awaited_once()


async def test_llm_reply_node_llm_failure_pushes_error(mock_llm, mock_emails_store, mock_user_profile_store, mock_push_callback):
    """Test llm_reply_node pushes error when LLM fails."""
    mock_llm.client.chat.completions.create.side_effect = Exception("LLM down")

    state: FreeChatState = {
        "messages": [{"role": "user", "content": "上次会议是啥时候？"}],
        "retrieved_emails": [42],
    }

    result = await llm_reply_node(
        state,
        llm=mock_llm,
        emails_store=mock_emails_store,
        user_profile_store=mock_user_profile_store,
        push_callback=mock_push_callback,
    )

    assert result == {}  # No messages appended
    mock_push_callback.assert_awaited_once_with("error", {
        "code": "chat_reply_failed",
        "message": "LLM down",
    })


def test_wait_user_node_returns_empty():
    """Test wait_user_node returns empty dict."""
    state: FreeChatState = {
        "messages": [{"role": "user", "content": "hi"}],
    }
    result = wait_user_node(state)
    assert result == {}


async def test_free_chat_graph_end_to_end(mock_llm, mock_embedding_client, mock_email_vec_store, mock_emails_store, mock_user_profile_store):
    """Test full free_chat graph flow with InMemorySaver."""
    push_callback = AsyncMock()

    # Build workflow
    workflow = build_free_chat_workflow(
        llm=mock_llm,
        embedding_client=mock_embedding_client,
        email_vec_store=mock_email_vec_store,
        emails_store=mock_emails_store,
        user_profile_store=mock_user_profile_store,
        push_callback=push_callback,
    )

    # Compile with MemorySaver AND interrupt_before
    app = workflow.compile(
        checkpointer=MemorySaver(),
        interrupt_before=["wait_user"],
    )

    # Initial state
    config = {"configurable": {"thread_id": "chat_default"}}
    initial_state: FreeChatState = {
        "messages": [{"role": "user", "content": "上次会议是啥时候？"}]
    }

    # Run graph until interrupt
    output = await app.ainvoke(initial_state, config)

    # Verify: should have assistant message
    assert "messages" in output
    # Messages should be appended via reducer
    assert len(output["messages"]) >= 1
    # Last message should be assistant
    assert output["messages"][-1]["role"] == "assistant"
    assert output["messages"][-1]["content"] == "根据邮件，上次会议是周三下午。"

    # Verify push_callback called
    push_callback.assert_awaited_once_with("chat_reply", {
        "thread_id": "chat_default",
        "reply": "根据邮件，上次会议是周三下午。",
        "retrieved": True,
        "retrieved_count": 3,
    })

    # Verify we're interrupted at wait_user
    state_after = app.get_state(config)
    assert "wait_user" in state_after.next
