"""LangGraph StateGraph assembly for the EmailPet agent.

See docs/modules/backend/emailpet/agent/graph.md for full module doc.
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
    """Build (but do not compile) the agent StateGraph.

    Compile separately with a checkpointer (and the appropriate
    interrupt_before list) — tests use an InMemorySaver, production uses
    AsyncSqliteSaver.
    """
    workflow: StateGraph = StateGraph(AgentState)

    # Inject dependencies via partial. LangGraph nodes are invoked with just
    # `state`; partial turns each multi-arg node into a state-only callable.
    workflow.add_node(
        "summarize",
        partial(summarize_node, llm=llm, push_callback=push_callback, emails_store=emails_store),
    )
    workflow.add_node(
        "silent_archive",
        partial(silent_archive_node, tools=tools, archive_log=archive_log),
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
        partial(execute_reply, tools=tools, push_callback=push_callback),
    )
    workflow.add_node(
        "execute_archive",
        partial(execute_archive, tools=tools, push_callback=push_callback),
    )
    workflow.add_node(
        "notify_skip",
        partial(notify_skip_node, push_callback=push_callback),
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
    """Build, compile, and return a runnable LangGraph agent with persistence.

    `AsyncSqliteSaver.from_conn_string` is an asynccontextmanager — we enter
    it here and return both the agent and the context manager so the caller
    can `__aexit__` it on shutdown.

    Returns:
        (compiled_agent, saver_cm) — caller must `await saver_cm.__aexit__(None, None, None)`
        when done (typically at process shutdown).
    """
    workflow = build_workflow(llm, tools, archive_log, profile_store, push_callback, emails_store, email_vec_store, embedding_client)
    Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
    saver_cm = AsyncSqliteSaver.from_conn_string(str(checkpoint_path))
    saver = await saver_cm.__aenter__()
    agent = workflow.compile(
        checkpointer=saver,
        interrupt_before=["wait_intent", "wait_decision"],
    )
    return agent, saver_cm
