"""自由对话 graph 的 state schema。

See docs/modules/backend/emailpet/agent/free_chat_state.md for full module doc.
"""
from __future__ import annotations

from typing import Annotated, TypedDict

import operator


class FreeChatState(TypedDict, total=False):
    """自由对话状态。thread_id = "chat_default"（单用户单会话）。

    messages 用 Annotated[list, operator.add] 让 update_state 时 append 而非覆盖。
    """

    messages: Annotated[list[dict], operator.add]
    retrieved_emails: list[int]
    thread_id: str
