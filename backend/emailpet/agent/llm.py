"""OpenAI-compatible LLM client for summarization and reply drafting.

See docs/modules/backend/emailpet/agent/llm.md for full module doc.
"""
from __future__ import annotations

import json
import logging
from typing import get_args

from openai import AsyncOpenAI

from emailpet.mail.models import Category, Draft, Summary, SuggestedAction

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """LLM 请求在重试后仍然失败。"""


# 发送给 LLM 前截断正文（摘要不需要全文）
MAX_BODY_CHARS_FOR_LLM = 10_000

CATEGORIES = set(get_args(Category))
ACTIONS = set(get_args(SuggestedAction))


SUMMARIZE_SYSTEM = (
    "你是一个邮件助手。分析用户给定的邮件内容，判断重要性、归类，"
    "并以纯 JSON（无 markdown 代码块）返回结果。"
)
SUMMARIZE_USER_TEMPLATE = (
    "请按以下 JSON 结构返回，**只输出 JSON，不要解释**：\n"
    '{{"summary": "一句话摘要", '
    '"is_important": true/false, '
    '"category": "work|personal|promo|notification", '
    '"needs_reply": true/false, '
    '"suggested_action": "reply|archive|skip"}}\n\n'
    "判断标准：\n"
    "- is_important=true：工作沟通、个人事务、紧急事项、明确需要用户回复或处理\n"
    "- is_important=false：广告、营销邮件、订阅通知、自动通知（密码重置确认这类）\n"
    "- needs_reply=true：需要用户回复（工作沟通、朋友邀约、客户咨询）\n"
    "- needs_reply=false：不需要回复（银行账单、订单通知、密码重置、noreply 类）\n"
    "- category 在四类中选一\n"
    "- suggested_action：reply（建议回复）、archive（直接归档）、skip（暂不处理）\n\n"
    "邮件内容：\n{body}"
)

DRAFT_SYSTEM = (
    "你是一个邮件助手，根据用户收到的邮件帮用户起草一封中文回复。"
    "以纯 JSON（无 markdown 代码块）返回结果。"
)
DRAFT_USER_TEMPLATE = (
    "请按以下 JSON 结构返回，**只输出 JSON，不要解释**：\n"
    '{{"body": "回复正文", "reason": "为什么这样回复（一句话）"}}\n\n'
    "原邮件内容：\n{body}\n\n"
    "{feedback_block}"
)


class LLMClient:
    """OpenAI 兼容的 LLM 客户端，用于摘要生成、回复草稿和画像学习。"""
    def __init__(self, base_url: str, api_key: str, model: str, token_store=None) -> None:
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.token_store = token_store

    async def extract_profile_patch(
        self, current_profile: dict, original_draft: str, user_feedback: str, email_body: str
    ) -> dict:
        """从用户反馈中提取画像更新补丁。

        Args:
            current_profile: 当前用户画像
            original_draft: 原始草稿
            user_feedback: 用户反馈/修改
            email_body: 原始邮件正文

        Returns:
            画像补丁 dict（只包含变化的字段）
        """
        # 延迟导入避免循环依赖
        from emailpet.agent.profile_update import PROFILE_SYSTEM, PROFILE_USER_TEMPLATE
        user_msg = PROFILE_USER_TEMPLATE.format(
            current_profile=json.dumps(current_profile, ensure_ascii=False),
            original_draft=original_draft,
            user_feedback=user_feedback,
            email_body=email_body,
        )
        return await self._call_json(PROFILE_SYSTEM, user_msg, call_type="profile_update")

    async def chat_completion(
        self, messages: list[dict], temperature: float = 0.5, call_type: str = "free_chat"
    ) -> str:
        """直接调用 chat completion（不走 _call_json），供 free_chat 用。记录 token。

        Args:
            messages: 对话消息列表
            temperature: 温度参数
            call_type: 调用类型，用于 token 统计

        Returns:
            LLM 生成的文本
        """
        completion = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
        )
        content = completion.choices[0].message.content or ""

        # 记录 token 用量
        if self.token_store is not None:
            usage = getattr(completion, "usage", None)
            if usage is not None:
                self.token_store.record(
                    call_type=call_type,
                    model=self.model,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    total_tokens=usage.total_tokens,
                )
            else:
                logger.warning("LLM completion.usage is None, recording 0 tokens for %s", call_type)
                self.token_store.record(
                    call_type=call_type,
                    model=self.model,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                )

        return content

    async def summarize(self, email_body: str) -> Summary:
        """生成邮件摘要并判断重要性、分类。

        Args:
            email_body: 邮件正文

        Returns:
            Summary 对象
            LLM 失败时返回降级摘要（标记为重要，建议回复）
        """
        body = _truncate(email_body)
        system = SUMMARIZE_SYSTEM
        user = SUMMARIZE_USER_TEMPLATE.format(body=body)
        try:
            data = await self._call_json(system, user, call_type="summarize")
            return _validate_summary(data)
        except (LLMError, ValueError) as e:
            logger.warning("summarize failed, fallback to important: %s", e)
            # 降级策略：失败时保守标记为重要，让用户人工处理
            return Summary(
                text="(LLM 未能生成摘要，请人工查看邮件原文)",
                is_important=True,
                category="work",
                suggested_action="reply",
                needs_reply=True,
            )

    async def draft_reply(self, original_body: str, feedback: str | None = None, profile_block: str = "") -> Draft:
        """生成回复草稿，可选带上用户反馈和用户画像。

        Args:
            original_body: 原始邮件正文
            feedback: 用户对上次草稿的反馈（可选）
            profile_block: 用户画像描述块（可选）

        Returns:
            Draft 对象

        Raises:
            LLMError: LLM 请求失败或 JSON 解析失败
        """
        body = _truncate(original_body)
        feedback_block = (
            f"用户对上次草稿的反馈：{feedback}\n请根据反馈重新起草。"
            if feedback
            else "这是首次起草。"
        )
        full_profile = f"\n\n{profile_block}" if profile_block else ""
        user = DRAFT_USER_TEMPLATE.format(body=body, feedback_block=feedback_block) + full_profile
        try:
            data = await self._call_json(DRAFT_SYSTEM, user, call_type="draft_reply")
            return _validate_draft(data)
        except (LLMError, ValueError) as e:
            raise LLMError(f"draft_reply failed: {e}") from e

    async def _call_json(self, system: str, user: str, call_type: str = "unknown") -> dict:
        """调用 LLM 并解析 JSON，JSON 解析失败时重试一次。

        Args:
            system: system prompt
            user: user prompt
            call_type: 调用类型，用于 token 统计

        Returns:
            解析后的 JSON dict

        Raises:
            LLMError: 两次尝试后仍解析失败
        """
        first_response = await self._call_text(system, user, call_type=call_type)
        try:
            return _extract_json(first_response)
        except ValueError:
            pass
        # 重试时加入纠正反馈
        retry_user = user + (
            "\n\n注意：上一次你的输出格式不正确，请严格输出合法 JSON，"
            "不要用 markdown 代码块，不要加任何解释。"
        )
        second_response = await self._call_text(system, retry_user, call_type=call_type)
        try:
            return _extract_json(second_response)
        except ValueError as e:
            raise LLMError(f"failed to parse JSON after retry: {e}") from e

    async def _call_text(self, system: str, user: str, call_type: str = "unknown") -> str:
        """调用 LLM 获取纯文本响应。

        Args:
            system: system prompt
            user: user prompt
            call_type: 调用类型，用于 token 统计

        Returns:
            LLM 生成的文本
        """
        completion = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,  # 较低温度使输出更稳定可预测
        )
        content = completion.choices[0].message.content or ""

        # 记录 token 用量
        if self.token_store is not None:
            usage = getattr(completion, "usage", None)
            if usage is not None:
                self.token_store.record(
                    call_type=call_type,
                    model=self.model,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    total_tokens=usage.total_tokens,
                )
            else:
                logger.warning("LLM completion.usage is None, recording 0 tokens for %s", call_type)
                self.token_store.record(
                    call_type=call_type,
                    model=self.model,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                )

        return content


def _truncate(body: str) -> str:
    """截断超长邮件正文，避免超出 LLM context window。"""
    if len(body) <= MAX_BODY_CHARS_FOR_LLM:
        return body
    return body[:MAX_BODY_CHARS_FOR_LLM] + "\n[...内容过长，已截断]"


def _extract_json(text: str) -> dict:
    """从 LLM 输出中提取 JSON 对象，容忍 ```json ... ``` 标记。

    Args:
        text: LLM 输出文本

    Returns:
        解析后的 JSON dict

    Raises:
        ValueError: 无法解析为 JSON
    """
    s = text.strip()
    # 去掉代码围栏（如果有）
    if s.startswith("```"):
        # 找到第一个换行和最后一个 ```
        parts = s.split("```")
        # parts: ['', 'json\n{...}\n', ''] 或 ['', '{...}', '']
        if len(parts) >= 2:
            inner = parts[1]
            if inner.lstrip().lower().startswith("json"):
                stripped = inner.lstrip()
                inner = stripped[4:].lstrip()
            s = inner.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        raise ValueError(f"not valid JSON: {text!r}") from e


def _validate_summary(data: dict) -> Summary:
    """验证 LLM 返回的摘要数据，确保所有必要字段存在且类型正确。

    Args:
        data: LLM 返回的 JSON dict

    Returns:
        Summary 对象

    Raises:
        ValueError: 字段缺失或值无效
    """
    for key in ("summary", "is_important", "category", "suggested_action", "needs_reply"):
        if key not in data:
            raise ValueError(f"summary missing field: {key}")
    if data["category"] not in CATEGORIES:
        raise ValueError(f"invalid category: {data['category']!r}")
    if data["suggested_action"] not in ACTIONS:
        raise ValueError(f"invalid suggested_action: {data['suggested_action']!r}")
    if not isinstance(data["is_important"], bool):
        raise ValueError("is_important must be bool")
    if not isinstance(data["needs_reply"], bool):
        raise ValueError("needs_reply must be bool")
    return Summary(
        text=str(data["summary"]),
        is_important=data["is_important"],
        category=data["category"],
        suggested_action=data["suggested_action"],
        needs_reply=data["needs_reply"],
    )


def _validate_draft(data: dict) -> Draft:
    """验证 LLM 返回的草稿数据，确保所有必要字段存在。

    Args:
        data: LLM 返回的 JSON dict

    Returns:
        Draft 对象

    Raises:
        ValueError: 字段缺失
    """
    for key in ("body", "reason"):
        if key not in data:
            raise ValueError(f"draft missing field: {key}")
    return Draft(body=str(data["body"]), reason=str(data["reason"]))
