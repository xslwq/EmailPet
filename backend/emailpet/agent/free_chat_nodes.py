"""自由对话 graph 的节点函数。
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from emailpet.agent.embedding import EmbeddingClient, EmbeddingError
from emailpet.agent.free_chat_state import FreeChatState
from emailpet.agent.llm import LLMClient

logger = logging.getLogger(__name__)

# Push callback 协议
PushCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


async def retrieve_node(
    state: FreeChatState,
    embedding_client: EmbeddingClient,
    email_vec_store: Any,
    emails_store: Any,
) -> dict[str, Any]:
    """把用户最后一条消息向量化，查 email_vec top-5，存 uid 到 state。

    Args:
        state: 当前自由对话状态
        embedding_client: embedding 客户端
        email_vec_store: 向量索引存储
        emails_store: 邮件存储（本节点不直接使用，但为保持签名一致性保留）

    Returns:
        {"retrieved_emails": list[uid]} 或降级为空列表
    """
    messages = state.get("messages", [])
    if not messages:
        return {"retrieved_emails": []}

    # 找最后一条用户消息
    last_user_msg = next((m for m in reversed(messages) if m.get("role") == "user"), None)
    if last_user_msg is None:
        return {"retrieved_emails": []}

    content = last_user_msg.get("content", "")
    if not content.strip():
        return {"retrieved_emails": []}

    try:
        query_embedding = await embedding_client.embed(content)
        uids = email_vec_store.query(query_embedding, k=5)
        return {"retrieved_emails": uids}
    except EmbeddingError as e:
        logger.warning("retrieve_node embedding failed, degrading: %s", e)
        return {"retrieved_emails": []}
    except Exception as e:  # noqa: BLE001
        logger.warning("retrieve_node unexpected error, degrading: %s", e)
        return {"retrieved_emails": []}


async def llm_reply_node(
    state: FreeChatState,
    llm: LLMClient,
    emails_store: Any,
    user_profile_store: Any,
    push_callback: PushCallback,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """拼检索邮件 + 画像 + 对话历史 → LLM 回复 → push chat_reply。

    Args:
        state: 当前自由对话状态
        llm: LLM 客户端
        emails_store: 邮件存储
        user_profile_store: 用户画像存储（可为 None）
        push_callback: WebSocket 推送回调
        thread_id: 线程 ID（默认 "chat_default"）

    Returns:
        {"messages": [assistant_msg]} 或失败时返回 {}
    """
    retrieved_uids = state.get("retrieved_emails", [])
    actual_thread_id = thread_id or "chat_default"

    # 拼检索邮件文本
    retrieved_blocks = []
    for uid in retrieved_uids:
        row = emails_store.get_by_uid(uid)
        if row:
            retrieved_blocks.append(
                f"- [{row.get('sender_name', '未知')}] {row.get('subject', '无主题')}\n"
                f"  摘要：{row.get('summary', '无摘要')}\n"
                f"  时间：{row.get('received_at', '未知时间')}\n"
                f"  用户处理：{row.get('user_action', '未处理')}"
            )
    retrieved_text = "\n".join(retrieved_blocks) if retrieved_blocks else "（无相关邮件）"

    # 拼 user_profile（可选）
    profile_text = ""
    if user_profile_store is not None:
        profile = user_profile_store.get()
        if profile.get("display_name"):
            profile_text += f"用户称呼：{profile['display_name']}\n"
        if profile.get("tone"):
            profile_text += f"语气偏好：{profile['tone']}\n"

    system_prompt = (
        "你是用户的邮件助手小猫。基于以下信息回答用户问题。\n\n"
        f"用户画像：\n{profile_text or '（暂无）'}\n\n"
        f"相关历史邮件：\n{retrieved_text}\n\n"
        "回答要简洁、口语化。如果检索邮件里没有答案，坦诚说不知道。"
    )

    messages_for_llm = [{"role": "system", "content": system_prompt}] + state.get("messages", [])

    try:
        reply = await llm.chat_completion(
            messages_for_llm,
            temperature=0.5,
            call_type="free_chat",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("llm_reply failed: %s", e)
        await push_callback("error", {"code": "chat_reply_failed", "message": str(e)})
        return {}  # 不 append，让 graph 继续

    # push chat_reply 给前端
    await push_callback("chat_reply", {
        "thread_id": actual_thread_id,
        "reply": reply,
        "retrieved": len(retrieved_uids) > 0,
        "retrieved_count": len(retrieved_uids),
    })

    # append assistant 消息到 state.messages（用 Annotated reducer，返回 [msg] 会被 append）
    return {"messages": [{"role": "assistant", "content": reply}]}


def wait_user_node(state: FreeChatState) -> dict[str, Any]:
    """pass-through，interrupt 点。等用户下一条消息后 resume。

    Args:
        state: 当前自由对话状态

    Returns:
        {}（不修改 state）
    """
    return {}
