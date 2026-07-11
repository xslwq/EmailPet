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
    emails_store: Any = None,
) -> dict[str, Any]:
    """从 pending_emails 取出第一封邮件，通过 LLM 生成摘要，写入 state 和 emails_store。

    Args:
        state: 当前 agent state
        llm: LLM 客户端
        push_callback: WebSocket 推送回调
        emails_store: 邮件存储（可选）

    Returns:
        更新后的 state 字段：current_email, current_summary, pending_emails（移除已处理的邮件）
    """
    pending = list(state.get("pending_emails", []))
    if not pending:
        logger.warning("summarize_node called with empty pending_emails")
        return {}
    email = pending[0]
    summary = await llm.summarize(email.body_text)
    if emails_store is not None:
        emails_store.upsert(email, summary)
    return {
        "current_email": email,
        "current_summary": summary,
        "pending_emails": pending[1:],  # 从队列移除已处理邮件
    }


async def silent_archive_node(
    state: AgentState,
    tools: AgentTools,
    archive_log: Any,  # ArchiveLog interface — duck-typed for test simplicity
    emails_store: Any = None,
) -> dict[str, Any]:
    """静默归档不重要的邮件，写入本地日志，不通知用户。

    Args:
        state: 当前 agent state
        tools: 邮件操作工具
        archive_log: 归档日志记录器
        emails_store: 邮件存储（可选）

    Returns:
        空 dict（不修改 state）
    """
    email = state.get("current_email")
    summary = state.get("current_summary")
    if email is None or summary is None:
        logger.warning("silent_archive_node missing current_email/summary")
        return {}
    result = await tools.archive(email)
    if result.get("status") != "archived":
        logger.warning("silent_archive failed for uid=%s: %s", email.uid, result)
    else:
        if emails_store is not None:
            emails_store.update_action(email.uid, "archived")
    try:
        archive_log.log(email, summary.category)
    except Exception as e:  # noqa: BLE001
        logger.warning("archive_log.log failed: %s", e)
    return {}


async def notify_summary_node(
    state: AgentState,
    push_callback: PushCallback,
    emails_store: Any = None,
    email_vec_store: Any = None,
    embedding_client: Any = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """通过 WebSocket 向用户推送摘要事件，然后构建向量索引用于后续搜索。

    Args:
        state: 当前 agent state
        push_callback: WebSocket 推送回调
        emails_store: 邮件存储（可选）
        email_vec_store: 向量索引存储（可选）
        embedding_client: 嵌入模型客户端（可选）
        thread_id: 线程 ID（可选，默认从 email.uid 生成）

    Returns:
        空 dict（不修改 state）
    """
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
    # 向量索引构建失败不影响主流程，只记录警告
    if embedding_client is not None and email_vec_store is not None and emails_store is not None:
        try:
            doc = f"{email.subject}\n{email.body_text}\n{summary.text}"
            embedding = await embedding_client.embed(doc)
            email_vec_store.index(email.uid, embedding)
            emails_store.mark_indexed(email.uid)
        except Exception as e:  # noqa: BLE001
            logger.warning("vector index build failed for uid=%s: %s", email.uid, e)
    return {}


def wait_intent_node(state: AgentState) -> dict[str, Any]:
    """中断点占位节点：等待用户选择意图（回复/归档/跳过）。

    图编译时设置了 interrupt_before=["wait_intent"]，运行时到达此节点会暂停。
    用户通过 update_state 提供 current_intent 后，图会继续运行并路由到对应分支。

    Args:
        state: 当前 agent state

    Returns:
        空 dict（不修改 state）
    """
    return {}


def wait_decision_node(state: AgentState) -> dict[str, Any]:
    """第二个中断点占位节点：等待用户对草稿的决定（批准/修改/拒绝）。

    位于 draft_reply 之后。用户通过 update_state 提供 draft_decision 后，
    图会根据决定路由到对应分支。

    Args:
        state: 当前 agent state

    Returns:
        空 dict（不修改 state）
    """
    return {}


async def draft_reply_node(
    state: AgentState,
    llm: LLMClient,
    push_callback: PushCallback,
    profile_store: Any = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """通过 LLM 生成回复草稿，推送给用户，并存储在 state 中。

    Args:
        state: 当前 agent state
        llm: LLM 客户端
        push_callback: WebSocket 推送回调
        profile_store: 用户画像存储（可选）
        thread_id: 线程 ID（可选）

    Returns:
        更新后的 state 字段：current_draft, original_draft, user_feedback（清空）
        失败时返回 draft_decision: "reject" 短路到结束
    """
    email = state.get("current_email")
    if email is None:
        logger.warning("draft_reply_node missing current_email")
        return {}
    feedback = state.get("user_feedback")
    profile_block = _build_profile_block(profile_store) if profile_store else ""
    try:
        draft = await llm.draft_reply(email.body_text, feedback=feedback, profile_block=profile_block)
    except LLMError as e:
        logger.warning("draft_reply LLM failure: %s", e)
        await push_callback("error", {"code": "llm_draft_failed", "message": str(e)})
        return {"draft_decision": "reject"}  # LLM 失败时直接短路到结束
    payload = {
        "thread_id": thread_id or f"email_{email.uid}",
        "draft": draft.body,
        "reason": draft.reason,
    }
    await push_callback("draft", payload)
    # 清空 feedback，避免下次迭代重复应用
    return {"current_draft": draft, "original_draft": draft, "user_feedback": None}


def _build_profile_block(profile_store: Any) -> str:
    """从用户画像存储构建自然语言风格描述块，注入到 LLM prompt 中。

    Args:
        profile_store: 用户画像存储

    Returns:
        格式化的用户风格描述字符串，为空时返回空字符串
    """
    profile = profile_store.get()
    parts = []
    if profile.get("display_name"):
        parts.append(f"称呼：{profile['display_name']}")
    if profile.get("signature"):
        parts.append(f"签名：{profile['signature']}")
    if profile.get("tone"):
        parts.append(f"语气：{profile['tone']}")
    if profile.get("honorific") is not None:
        parts.append(f"敬语：{'使用' if profile['honorific'] else '不使用'}")
    if profile.get("common_phrases"):
        parts.append(f"常用话术：{', '.join(profile['common_phrases'])}")
    if not parts:
        return ""
    return "用户回复风格偏好：\n" + "\n".join(parts)


async def execute_reply(
    state: AgentState,
    tools: AgentTools,
    push_callback: PushCallback,
    emails_store: Any = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """通过 SMTP 发送草稿，推送 'sent' 事件，更新邮件存储。

    Args:
        state: 当前 agent state
        tools: 邮件操作工具
        push_callback: WebSocket 推送回调
        emails_store: 邮件存储（可选）
        thread_id: 线程 ID（可选）

    Returns:
        更新后的 state 字段：current_draft（清空）
    """
    email = state.get("current_email")
    draft = state.get("current_draft")
    if email is None or draft is None:
        logger.warning("execute_reply missing email/draft")
        return {}
    result = await tools.reply(email, draft.body)
    if result.get("status") == "sent":
        if emails_store is not None:
            emails_store.update_action(email.uid, "replied", replied_body=draft.body)
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
    emails_store: Any = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """归档当前邮件（用户主动操作，非静默）。

    与 silent_archive 不同，此路径是用户驱动的，需要推送确认事件让用户感知。

    Args:
        state: 当前 agent state
        tools: 邮件操作工具
        push_callback: WebSocket 推送回调
        emails_store: 邮件存储（可选）
        thread_id: 线程 ID（可选）

    Returns:
        空 dict（不修改 state）
    """
    email = state.get("current_email")
    if email is None:
        return {}
    result = await tools.archive(email)
    if result.get("status") == "archived":
        if emails_store is not None:
            emails_store.update_action(email.uid, "archived")
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
    emails_store: Any = None,
) -> dict[str, Any]:
    """确认用户的"跳过"意图，给用户一个闭环反馈。

    当用户在摘要气泡上选择"跳过"时到达此节点——否则图会静默结束，
    用户不知道桌宠是否接收到了指令。

    Args:
        state: 当前 agent state
        push_callback: WebSocket 推送回调
        emails_store: 邮件存储（可选）

    Returns:
        空 dict（不修改 state）
    """
    email = state.get("current_email")
    if email is not None and emails_store is not None:
        emails_store.update_action(email.uid, "skipped")
    await push_callback("agent_say", {"text": "好，先放着不管。"})
    return {}


async def notify_reject_node(
    state: AgentState,
    push_callback: PushCallback,
) -> dict[str, Any]:
    """确认用户对草稿的"拒绝"决定。

    与 notify_skip_node 同理——图静默结束会让用户感觉系统卡住了。

    Args:
        state: 当前 agent state
        push_callback: WebSocket 推送回调

    Returns:
        空 dict（不修改 state）
    """
    await push_callback("agent_say", {"text": "好，这封不回了。"})
    return {}


# -------------------- Conditional routers --------------------


def is_important_condition(state: AgentState) -> str:
    """条件路由：根据邮件重要性决定是静默归档还是通知用户。

    Args:
        state: 当前 agent state

    Returns:
        "silent_archive" | "notify_summary"
    """
    summary = state.get("current_summary")
    if summary is None or not summary.is_important:
        return "silent_archive"
    return "notify_summary"


def route_intent(state: AgentState) -> str:
    """条件路由：根据用户意图决定下一步（回复/归档/跳过）。

    Args:
        state: 当前 agent state

    Returns:
        "draft_reply" | "execute_archive" | "notify_skip"
    """
    intent = state.get("current_intent")
    if intent == "reply":
        return "draft_reply"
    if intent == "archive":
        return "execute_archive"
    return "notify_skip"  # "skip" 或未设置 → 确认后结束


def route_decision(state: AgentState) -> str:
    """条件路由：根据用户对草稿的决定路由（发送/修改画像/拒绝）。

    Args:
        state: 当前 agent state

    Returns:
        "execute_reply" | "profile_update" | "notify_reject"
    """
    decision = state.get("draft_decision")
    if decision == "approve":
        return "execute_reply"
    if decision == "modify":
        return "profile_update"
    return "notify_reject"  # "reject" 或未设置 → 确认后结束
