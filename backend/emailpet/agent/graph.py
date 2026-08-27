"""LangGraph StateGraph assembly for the EmailPet agent.
"""
from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any, Awaitable, Callable

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, StateGraph

from emailpet.agent.llm import LLMClient
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
    wait_decision_node,
    wait_intent_node,
)
from emailpet.agent.profile_update import profile_update_node
from emailpet.agent.state import AgentState
from emailpet.agent.tools import AgentTools
from emailpet.agent.embedding import EmbeddingClient
from emailpet.storage.archive_log import ArchiveLog
from emailpet.storage.email_vec_store import EmailVecStore
from emailpet.storage.emails_store import EmailsStore
from emailpet.storage.user_profile_store import UserProfileStore

PushCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


def build_workflow(
    llm: LLMClient,
    tools: AgentTools,
    archive_log: ArchiveLog,
    profile_store: UserProfileStore,
    push_callback: PushCallback,
    emails_store: EmailsStore | None = None,
    email_vec_store: EmailVecStore | None = None,
    embedding_client: EmbeddingClient | None = None,
) -> StateGraph:
    """构建（但不编译）agent StateGraph。

    单独编译时添加 checkpointer 和 interrupt_before 列表——测试用 InMemorySaver，
    生产环境用 AsyncSqliteSaver。

    Args:
        llm: LLM 客户端
        tools: 邮件操作工具
        archive_log: 归档日志
        profile_store: 用户画像存储
        push_callback: WebSocket 推送回调
        emails_store: 邮件存储（可选）
        email_vec_store: 向量索引存储（可选）
        embedding_client: 嵌入模型客户端（可选）

    Returns:
        配置好节点和边的 StateGraph（未编译）
    """
    workflow: StateGraph = StateGraph(AgentState)

    # 通过 partial 注入依赖。LangGraph 节点只用 `state` 调用；
    # partial 将多参数节点转换为仅接受 state 的可调用对象。
    workflow.add_node(
        "summarize",
        partial(summarize_node, llm=llm, push_callback=push_callback, emails_store=emails_store),
    )
    workflow.add_node(
        "silent_archive",
        partial(silent_archive_node, tools=tools, archive_log=archive_log, emails_store=emails_store),
    )
    workflow.add_node(
        "notify_summary",
        partial(notify_summary_node, push_callback=push_callback, emails_store=emails_store, email_vec_store=email_vec_store, embedding_client=embedding_client),
    )
    workflow.add_node("wait_intent", wait_intent_node)
    workflow.add_node(
        "draft_reply",
        partial(draft_reply_node, llm=llm, push_callback=push_callback, profile_store=profile_store),
    )
    workflow.add_node("wait_decision", wait_decision_node)
    workflow.add_node(
        "execute_reply",
        partial(execute_reply, tools=tools, push_callback=push_callback, emails_store=emails_store),
    )
    workflow.add_node(
        "execute_archive",
        partial(execute_archive, tools=tools, push_callback=push_callback, emails_store=emails_store),
    )
    workflow.add_node(
        "notify_skip",
        partial(notify_skip_node, push_callback=push_callback, emails_store=emails_store),
    )
    workflow.add_node(
        "notify_reject",
        partial(notify_reject_node, push_callback=push_callback),
    )
    workflow.add_node(
        "profile_update",
        partial(profile_update_node, llm=llm, profile_store=profile_store, push_callback=push_callback),
    )

    workflow.set_entry_point("summarize")
    workflow.add_conditional_edges(
        "summarize",
        is_important_condition,
        {
            "silent_archive": "silent_archive",
            "notify_summary": "notify_summary",
        },
    )
    workflow.add_edge("silent_archive", END)
    workflow.add_edge("notify_summary", "wait_intent")
    workflow.add_conditional_edges(
        "wait_intent",
        route_intent,
        {
            "draft_reply": "draft_reply",
            "execute_archive": "execute_archive",
            "notify_skip": "notify_skip",
        },
    )
    workflow.add_edge("draft_reply", "wait_decision")
    workflow.add_conditional_edges(
        "wait_decision",
        route_decision,
        {
            "execute_reply": "execute_reply",
            "profile_update": "profile_update",
            "notify_reject": "notify_reject",
        },
    )
    # profile_update 后回到 draft_reply 重新生成草稿，形成修改循环
    workflow.add_edge("profile_update", "draft_reply")
    workflow.add_edge("execute_reply", END)
    workflow.add_edge("execute_archive", END)
    workflow.add_edge("notify_skip", END)
    workflow.add_edge("notify_reject", END)

    return workflow


async def build_agent(
    llm: LLMClient,
    tools: AgentTools,
    archive_log: ArchiveLog,
    profile_store: UserProfileStore,
    push_callback: PushCallback,
    checkpoint_path: str | Path,
    emails_store: EmailsStore | None = None,
    email_vec_store: EmailVecStore | None = None,
    embedding_client: EmbeddingClient | None = None,
):
    """构建、编译并返回带持久化的可运行 LangGraph agent。

    `AsyncSqliteSaver.from_conn_string` 是 asynccontextmanager——我们在这里进入它，
    同时返回 agent 和 context manager，让调用者在关闭时可以 `__aexit__`。

    Args:
        llm: LLM 客户端
        tools: 邮件操作工具
        archive_log: 归档日志
        profile_store: 用户画像存储
        push_callback: WebSocket 推送回调
        checkpoint_path: checkpoint 数据库文件路径
        emails_store: 邮件存储（可选）
        email_vec_store: 向量索引存储（可选）
        embedding_client: 嵌入模型客户端（可选）

    Returns:
        (compiled_agent, saver_cm) — 调用者完成后必须
        `await saver_cm.__aexit__(None, None, None)`（通常在进程关闭时）
    """
    workflow = build_workflow(llm, tools, archive_log, profile_store, push_callback, emails_store, email_vec_store, embedding_client)
    # 确保 checkpoint 目录存在
    Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
    saver_cm = AsyncSqliteSaver.from_conn_string(str(checkpoint_path))
    saver = await saver_cm.__aenter__()
    # 设置两个中断点：等待用户意图、等待草稿决定
    agent = workflow.compile(
        checkpointer=saver,
        interrupt_before=["wait_intent", "wait_decision"],
    )
    return agent, saver_cm
