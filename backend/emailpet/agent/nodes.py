"""LangGraph node functions and conditional routers for the EmailPet agent.

See docs/modules/backend/emailpet/agent/nodes.md for full module doc.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from langgraph.graph import END

from emailpet.agent.llm import LLMClient, LLMError
from emailpet.agent.state import AgentState
from emailpet.agent.tools import AgentTools

logger = logging.getLogger(__name__)

# Push callback signature: async (event_type: str, payload: dict) -> None
PushCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


# -------------------- Nodes --------------------


async def summarize_node(
    state: AgentState,
    llm: LLMClient,
    push_callback: PushCallback,
) -> dict[str, Any]:
    """Pop pending_emails[0], summarize via LLM, write to state."""
    pending = list(state.get("pending_emails", []))
    if not pending:
        logger.warning("summarize_node called with empty pending_emails")
        return {}
    email = pending[0]
    summary = await llm.summarize(email.body_text)
    return {
        "current_email": email,
        "current_summary": summary,
        "pending_emails": pending[1:],
    }


async def silent_archive_node(
    state: AgentState,
    tools: AgentTools,
    archive_log: Any,  # ArchiveLog interface — duck-typed for test simplicity
) -> dict[str, Any]:
    """Silently archive a not-important email + write to local log."""
    email = state.get("current_email")
    summary = state.get("current_summary")
    if email is None or summary is None:
        logger.warning("silent_archive_node missing current_email/summary")
        return {}
    result = await tools.archive(email)
    if result.get("status") != "archived":
        logger.warning("silent_archive failed for uid=%s: %s", email.uid, result)
    try:
        archive_log.log(email, summary.category)
    except Exception as e:  # noqa: BLE001
        logger.warning("archive_log.log failed: %s", e)
    return {}


async def notify_summary_node(
    state: AgentState,
    push_callback: PushCallback,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Push the summary event to the user via WebSocket. State unchanged."""
    email = state.get("current_email")
    summary = state.get("current_summary")
    if email is None or summary is None:
        logger.warning("notify_summary_node missing current_email/summary")
        return {}
    payload = {
        "thread_id": thread_id or f"email_{email.uid}",
        "email": {
            "from_name": email.from_name,
            "from_address": email.from_address,
            "subject": email.subject,
            "received_at": email.received_at.isoformat(),
        },
        "summary": summary.text,
        "body_text": email.body_text,
        "suggested_action": summary.suggested_action,
        "needs_reply": summary.needs_reply,
    }
    await push_callback("summary", payload)
    return {}


def wait_intent_node(state: AgentState) -> dict[str, Any]:
    """Pass-through node that lives at the interrupt point.

    The graph is compiled with interrupt_before=["wait_intent"], so when
    the runtime reaches this node, it pauses. After the user's decision
    is supplied via update_state, this node runs and the graph routes
    based on current_intent.
    """
    return {}


def wait_decision_node(state: AgentState) -> dict[str, Any]:
    """Pass-through node that lives at the second interrupt point.

    Sits after draft_reply. The graph is compiled with
    interrupt_before=["wait_intent", "wait_decision"], so when the runtime
    reaches this node, it pauses. After the user's draft_decision is
    supplied via update_state, this node runs and the graph routes based
    on draft_decision (approve | modify | reject).
    """
    return {}


async def draft_reply_node(
    state: AgentState,
    llm: LLMClient,
    push_callback: PushCallback,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Generate a reply draft via LLM, push it to the user, store in state."""
    email = state.get("current_email")
    if email is None:
        logger.warning("draft_reply_node missing current_email")
        return {}
    feedback = state.get("user_feedback")
    try:
        draft = await llm.draft_reply(email.body_text, feedback=feedback)
    except LLMError as e:
        logger.warning("draft_reply LLM failure: %s", e)
        await push_callback("error", {"code": "llm_draft_failed", "message": str(e)})
        return {"draft_decision": "reject"}  # short-circuit to END via router
    payload = {
        "thread_id": thread_id or f"email_{email.uid}",
        "draft": draft.body,
        "reason": draft.reason,
    }
    await push_callback("draft", payload)
    # clear feedback so next iteration doesn't double-apply it
    return {"current_draft": draft, "original_draft": draft, "user_feedback": None}


async def execute_reply(
    state: AgentState,
    tools: AgentTools,
    push_callback: PushCallback,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Send the draft via SMTP, push 'sent' event."""
    email = state.get("current_email")
    draft = state.get("current_draft")
    if email is None or draft is None:
        logger.warning("execute_reply missing email/draft")
        return {}
    result = await tools.reply(email, draft.body)
    if result.get("status") == "sent":
        await push_callback(
            "sent",
            {"thread_id": thread_id or f"email_{email.uid}", "email_id": str(email.uid)},
        )
    else:
        await push_callback(
            "error",
            {
                "code": "send_failed",
                "message": result.get("message", "unknown send failure"),
            },
        )
    return {"current_draft": None}


async def execute_archive(
    state: AgentState,
    tools: AgentTools,
    push_callback: PushCallback,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Archive the current email (user-initiated, not silent).

    Unlike silent_archive, this path is user-driven so we DO push a
    confirmation event. Silent_archive stays quiet by design.
    """
    email = state.get("current_email")
    if email is None:
        return {}
    result = await tools.archive(email)
    if result.get("status") == "archived":
        await push_callback(
            "agent_say",
            {"text": f"好的，已归档：{email.subject[:30]}"},
        )
    else:
        await push_callback(
            "error",
            {
                "code": "archive_failed",
                "message": result.get("message", "归档失败"),
            },
        )
    return {}


async def notify_skip_node(
    state: AgentState,
    push_callback: PushCallback,
) -> dict[str, Any]:
    """Acknowledge a 'skip' intent so the user gets closure.

    Reached when the user picks 'skip' on a summary bubble — graph would
    otherwise silently end and the user wouldn't know the cat heard them.
    """
    await push_callback("agent_say", {"text": "好，先放着不管。"})
    return {}


async def notify_reject_node(
    state: AgentState,
    push_callback: PushCallback,
) -> dict[str, Any]:
    """Acknowledge a 'reject' decision on a draft reply.

    Same reason as notify_skip_node — graph reaching END silently feels
    broken from the user's POV.
    """
    await push_callback("agent_say", {"text": "好，这封不回了。"})
    return {}


# -------------------- Conditional routers --------------------


def is_important_condition(state: AgentState) -> str:
    summary = state.get("current_summary")
    if summary is None or not summary.is_important:
        return "silent_archive"
    return "notify_summary"


def route_intent(state: AgentState) -> str:
    intent = state.get("current_intent")
    if intent == "reply":
        return "draft_reply"
    if intent == "archive":
        return "execute_archive"
    return "notify_skip"  # "skip" or unset → acknowledge, then END


def route_decision(state: AgentState) -> str:
    decision = state.get("draft_decision")
    if decision == "approve":
        return "execute_reply"
    if decision == "modify":
        return "profile_update"
    return "notify_reject"  # "reject" or unset → acknowledge, then END
