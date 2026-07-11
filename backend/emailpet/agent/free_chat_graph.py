"""自由对话 LangGraph 组装。

See docs/modules/backend/emailpet/agent/free_chat_graph.md for full module doc.
"""
from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any, Awaitable, Callable

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import StateGraph

from emailpet.agent.embedding import EmbeddingClient
from emailpet.agent.free_chat_nodes import llm_reply_node, retrieve_node, wait_user_node, PushCallback
from emailpet.agent.free_chat_state import FreeChatState
from emailpet.agent.llm import LLMClient
from emailpet.storage.email_vec_store import EmailVecStore
from emailpet.storage.emails_store import EmailsStore
from emailpet.storage.user_profile_store import UserProfileStore


def build_free_chat_workflow(
    llm: LLMClient,
    embedding_client: EmbeddingClient,
    email_vec_store: EmailVecStore,
    emails_store: EmailsStore,
    user_profile_store: UserProfileStore,
    push_callback: PushCallback,
) -> StateGraph:
    """构建（但不编译）自由对话 StateGraph。

    Args:
        llm: LLM 客户端
        embedding_client: embedding 客户端
        email_vec_store: 向量索引存储
        emails_store: 邮件存储
        user_profile_store: 用户画像存储
        push_callback: WebSocket 推送回调

    Returns:
        配置好节点和边的 StateGraph（未编译）
    """
    workflow: StateGraph = StateGraph(FreeChatState)

    # 通过 partial 注入依赖
    workflow.add_node(
        "retrieve",
        partial(
            retrieve_node,
            embedding_client=embedding_client,
            email_vec_store=email_vec_store,
            emails_store=emails_store,
        ),
    )
    workflow.add_node(
        "llm_reply",
        partial(
            llm_reply_node,
            llm=llm,
            emails_store=emails_store,
            user_profile_store=user_profile_store,
            push_callback=push_callback,
        ),
    )
    workflow.add_node("wait_user", wait_user_node)

    workflow.set_entry_point("retrieve")
    workflow.add_edge("retrieve", "llm_reply")
    workflow.add_edge("llm_reply", "wait_user")
    workflow.add_edge("wait_user", "retrieve")  # 循环：用户下一条消息后回 retrieve

    return workflow


async def build_free_chat_agent(
    llm: LLMClient,
    embedding_client: EmbeddingClient,
    email_vec_store: EmailVecStore,
    emails_store: EmailsStore,
    user_profile_store: UserProfileStore,
    push_callback: PushCallback,
    checkpoint_path: str | Path,
) -> tuple[Any, Any]:
    """编译 free_chat graph + AsyncSqliteSaver。

    用独立的 checkpoint db（或与邮件 graph 共享，thread_id 区分）。
    interrupt_before=["wait_user"]：llm_reply 后暂停，等用户下一条消息。

    Args:
        llm: LLM 客户端
        embedding_client: embedding 客户端
        email_vec_store: 向量索引存储
        emails_store: 邮件存储
        user_profile_store: 用户画像存储
        push_callback: WebSocket 推送回调
        checkpoint_path: checkpoint 数据库文件路径

    Returns:
        (compiled_agent, saver_cm) — 调用者完成后必须
        await saver_cm.__aexit__(None, None, None)（通常在进程关闭时）
    """
    workflow = build_free_chat_workflow(
        llm,
        embedding_client,
        email_vec_store,
        emails_store,
        user_profile_store,
        push_callback,
    )

    # 确保 checkpoint 目录存在
    Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)

    saver_cm = AsyncSqliteSaver.from_conn_string(str(checkpoint_path))
    saver = await saver_cm.__aenter__()

    agent = workflow.compile(
        checkpointer=saver,
        interrupt_before=["wait_user"],
    )

    return agent, saver_cm
