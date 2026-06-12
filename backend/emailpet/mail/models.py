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
    """An email message fetched from IMAP."""
    uid: int
    folder: str
    from_name: str
    from_address: str
    subject: str
    body_text: str
    received_at: datetime


@dataclass(frozen=True)
class Summary:
    """LLM-generated summary + classification of an email."""
    text: str
    is_important: bool
    category: Category
    suggested_action: SuggestedAction


@dataclass(frozen=True)
class Draft:
    """LLM-generated reply draft."""
    body: str
    reason: str


@dataclass(frozen=True)
class Proposal:
    """A summary plus an optional draft (used during reply flow)."""
    summary: Summary
    draft: Draft | None = None
