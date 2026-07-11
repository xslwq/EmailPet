"""LangGraph state schema for the EmailPet agent.

See docs/modules/backend/emailpet/agent/state.md for full module doc.
"""
from __future__ import annotations

from typing import Optional, TypedDict

from emailpet.mail.models import Draft, Email, Summary


class AgentState(TypedDict, total=False):
    """每封邮件的 agent state。每个 email UID 对应一个 thread_id。

    所有字段都是可选的（TypedDict total=False），因为图在节点执行过程中
    逐步填充这些字段。
    """

    pending_emails: list[Email]
    current_email: Optional[Email]
    current_summary: Optional[Summary]
    current_intent: Optional[str]   # "reply" | "archive" | "skip"
    current_draft: Optional[Draft]
    original_draft: Optional[Draft]  # 画像提取用：modify 时的原始草稿
    draft_decision: Optional[str]   # "approve" | "modify" | "reject"
    user_feedback: Optional[str]
    history: list[dict]             # [{role: str, content: str}, ...]
