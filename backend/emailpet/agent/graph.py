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
    notify_summary_node,
    route_decision,
    route_intent,
    silent_archive_node,
    summarize_node,
    wait_decision_node,
    wait_intent_node,
)
from emailpet.agent.state import AgentState
from emailpet.agent.tools import AgentTools
from emailpet.storage.archive_log import ArchiveLog

PushCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


def build_workflow(
    llm: LLMClient,
    tools: AgentTools,
    archive_log: ArchiveLog,
    push_callback: PushCallback,
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
        partial(summarize_node, llm=llm, push_callback=push_callback),
    )
    workflow.add_node(
        "silent_archive",
        partial(silent_archive_node, tools=tools, archive_log=archive_log),
    )
    workflow.add_node(
        "notify_summary",
        partial(notify_summary_node, push_callback=push_callback),
    )
    workflow.add_node("wait_intent", wait_intent_node)
    workflow.add_node(
        "draft_reply",
        partial(draft_reply_node, llm=llm, push_callback=push_callback),
    )
    workflow.add_node("wait_decision", wait_decision_node)
    workflow.add_node(
        "execute_reply",
        partial(execute_reply, tools=tools, push_callback=push_callback),
    )
    workflow.add_node(
        "execute_archive",
        partial(execute_archive, tools=tools),
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
            END: END,
        },
    )
    workflow.add_edge("draft_reply", "wait_decision")
    workflow.add_conditional_edges(
        "wait_decision",
        route_decision,
        {
            "execute_reply": "execute_reply",
            "draft_reply": "draft_reply",
            END: END,
        },
    )
    workflow.add_edge("execute_reply", END)
    workflow.add_edge("execute_archive", END)

    return workflow


async def build_agent(
    llm: LLMClient,
    tools: AgentTools,
    archive_log: ArchiveLog,
    push_callback: PushCallback,
    checkpoint_path: str | Path,
):
    """Build, compile, and return a runnable LangGraph agent with persistence.

    `AsyncSqliteSaver.from_conn_string` is an asynccontextmanager — we enter
    it here and return both the agent and the context manager so the caller
    can `__aexit__` it on shutdown.

    Returns:
        (compiled_agent, saver_cm) — caller must `await saver_cm.__aexit__(None, None, None)`
        when done (typically at process shutdown).
    """
    workflow = build_workflow(llm, tools, archive_log, push_callback)
    Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
    saver_cm = AsyncSqliteSaver.from_conn_string(str(checkpoint_path))
    saver = await saver_cm.__aenter__()
    agent = workflow.compile(
        checkpointer=saver,
        interrupt_before=["wait_intent", "wait_decision"],
    )
    return agent, saver_cm
