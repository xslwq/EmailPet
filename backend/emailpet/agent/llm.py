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
    """LLM request failed after retries."""


# truncate body before sending to LLM (LLM doesn't need the whole thing for summarization)
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
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self.model = model

    async def summarize(self, email_body: str) -> Summary:
        body = _truncate(email_body)
        system = SUMMARIZE_SYSTEM
        user = SUMMARIZE_USER_TEMPLATE.format(body=body)
        try:
            data = await self._call_json(system, user)
            return _validate_summary(data)
        except (LLMError, ValueError) as e:
            logger.warning("summarize failed, fallback to important: %s", e)
            return Summary(
                text="(LLM 未能生成摘要，请人工查看邮件原文)",
                is_important=True,
                category="work",
                suggested_action="reply",
                needs_reply=True,
            )

    async def draft_reply(self, original_body: str, feedback: str | None = None) -> Draft:
        body = _truncate(original_body)
        feedback_block = (
            f"用户对上次草稿的反馈：{feedback}\n请根据反馈重新起草。"
            if feedback
            else "这是首次起草。"
        )
        user = DRAFT_USER_TEMPLATE.format(body=body, feedback_block=feedback_block)
        try:
            data = await self._call_json(DRAFT_SYSTEM, user)
            return _validate_draft(data)
        except (LLMError, ValueError) as e:
            raise LLMError(f"draft_reply failed: {e}") from e

    async def _call_json(self, system: str, user: str) -> dict:
        """Call LLM with one retry on JSON parse failure."""
        first_response = await self._call_text(system, user)
        try:
            return _extract_json(first_response)
        except ValueError:
            pass
        # retry with corrective feedback
        retry_user = user + (
            "\n\n注意：上一次你的输出格式不正确，请严格输出合法 JSON，"
            "不要用 markdown 代码块，不要加任何解释。"
        )
        second_response = await self._call_text(system, retry_user)
        try:
            return _extract_json(second_response)
        except ValueError as e:
            raise LLMError(f"failed to parse JSON after retry: {e}") from e

    async def _call_text(self, system: str, user: str) -> str:
        completion = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
        )
        content = completion.choices[0].message.content or ""
        return content


def _truncate(body: str) -> str:
    if len(body) <= MAX_BODY_CHARS_FOR_LLM:
        return body
    return body[:MAX_BODY_CHARS_FOR_LLM] + "\n[...内容过长，已截断]"


def _extract_json(text: str) -> dict:
    """Extract a JSON object from LLM output, tolerating ```json ... ``` markers."""
    s = text.strip()
    # strip code fences if any
    if s.startswith("```"):
        # find first newline and last ```
        parts = s.split("```")
        # parts: ['', 'json\n{...}\n', '']  or ['', '{...}', '']
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
    for key in ("body", "reason"):
        if key not in data:
            raise ValueError(f"draft missing field: {key}")
    return Draft(body=str(data["body"]), reason=str(data["reason"]))
