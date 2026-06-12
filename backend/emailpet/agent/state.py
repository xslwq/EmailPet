"""LangGraph state schema for the EmailPet agent.

See docs/modules/backend/emailpet/agent/state.md for full module doc.
"""
from __future__ import annotations

from typing import Optional, TypedDict

from emailpet.mail.models import Draft, Email, Summary


class AgentState(TypedDict, total=False):
    """Per-email agent state. One thread_id per email UID.

    All fields are optional in practice (TypedDict total=False) because
    the graph populates them progressively as nodes execute.
    """

    pending_emails: list[Email]
    current_email: Optional[Email]
    current_summary: Optional[Summary]
    current_intent: Optional[str]   # "reply" | "archive" | "skip"
    current_draft: Optional[Draft]
    draft_decision: Optional[str]   # "approve" | "modify" | "reject"
    user_feedback: Optional[str]
    history: list[dict]             # [{role: str, content: str}, ...]
