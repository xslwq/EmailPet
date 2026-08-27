"""profile_update_node — LLM-driven user style profile learning.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

from emailpet.agent.llm import LLMClient, LLMError
from emailpet.agent.state import AgentState
from emailpet.storage.user_profile_store import UserProfileStore

logger = logging.getLogger(__name__)

PushCallback = Callable[[str, dict[str, Any]], Awaitable[None]]

PROFILE_SYSTEM = (
    "你是用户画像学习器。对比原始草稿和用户修改后的版本，"
    "提取用户的回复风格偏好。以纯 JSON（无 markdown 代码块）返回结果。"
)
PROFILE_USER_TEMPLATE = (
    "请按以下 JSON 结构返回，**只输出 JSON，不要解释**。"
    "字段可省略（只输出有变化的）。字段值为 null 表示无变化，跳过该字段：\n"
    '{{"display_name": "用户对自己的称呼", '
    '"signature": "签名", '
    '"tone": "formal|casual|friendly", '
    '"honorific": true|false, '
    '"common_phrases": ["新增的常用话术"]}}\n\n'
    "当前画像：{current_profile}\n"
    "原草稿：{original_draft}\n"
    "用户改后/反馈：{user_feedback}\n"
    "邮件正文：{email_body}"
)


async def profile_update_node(
    state: AgentState,
    llm: LLMClient,
    profile_store: UserProfileStore,
    push_callback: PushCallback,
) -> dict[str, Any]:
    """通过 LLM 对比原始草稿和用户反馈，提取用户风格偏好并更新画像。

    Args:
        state: 当前 agent state
        llm: LLM 客户端
        profile_store: 用户画像存储
        push_callback: WebSocket 推送回调

    Returns:
        更新后的 state 字段：original_draft（清空，避免重复处理）
    """
    original_draft = state.get("original_draft")
    if original_draft is None:
        return {}
    email = state.get("current_email")
    feedback = state.get("user_feedback") or ""
    current_profile = profile_store.get()
    try:
        data = await llm.extract_profile_patch(
            current_profile=current_profile,
            original_draft=original_draft.body,
            user_feedback=feedback,
            email_body=email.body_text if email else "",
        )
    except (LLMError, ValueError) as e:
        logger.warning("profile_update LLM failed: %s", e)
        await push_callback("error", {"code": "profile_update_failed", "message": str(e)})
        return {"original_draft": None}
    if not isinstance(data, dict):
        logger.warning("profile_update non-dict response: %r", data)
        return {"original_draft": None}
    # 合并新提取的画像数据到现有画像
    profile_store.merge(data)
    return {"original_draft": None}
