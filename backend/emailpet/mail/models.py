"""Pure data containers for email and AI outputs.

See docs/modules/backend/emailpet/mail/models.md for full module doc.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


Category = Literal["work", "personal", "promo", "notification"]
SuggestedAction = Literal["reply", "archive", "skip"]


@dataclass(frozen=True)
class Email:
    """从 IMAP 拉取的原始邮件。"""
    uid: int
    folder: str
    from_name: str
    from_address: str
    subject: str
    body_text: str
    received_at: datetime


@dataclass(frozen=True)
class Summary:
    """LLM 生成的邮件摘要 + 分类。"""
    text: str
    is_important: bool
    category: Category
    suggested_action: SuggestedAction
    needs_reply: bool


@dataclass(frozen=True)
class Draft:
    """LLM 生成的回复草稿。"""
    body: str
    reason: str


@dataclass(frozen=True)
class Proposal:
    """摘要 + 可选草稿（用于回复流程）。"""
    summary: Summary
    draft: Draft | None = None
