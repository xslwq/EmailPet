"""WebSocket routing and connection management for EmailPet.

See docs/modules/backend/emailpet/ws.md for full module doc.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any, Awaitable, Callable, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# An "agent-like" object exposes aupdate_state and ainvoke.
# We accept any object matching the protocol — typed loosely for testability.
AgentResume = Callable[[dict, dict], Awaitable[Any]]
AgentUpdate = Callable[[dict, dict], Awaitable[Any]]


PENDING_QUEUE_MAX = 50


class ConnectionManager:
    """Manage the (single) active WebSocket and route messages.

    Push-side: nodes call `push(event_type, payload)`. If a client is
    connected, sends immediately; otherwise buffers up to PENDING_QUEUE_MAX
    events for delivery on reconnect (via `resync`).

    Receive-side: `process_message(msg, agent)` dispatches by `type` field.
    """

    def __init__(self) -> None:
        self._ws: Optional[WebSocket] = None
        self._pending: deque[dict[str, Any]] = deque(maxlen=PENDING_QUEUE_MAX)
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._ws is not None

    async def attach(self, ws: WebSocket) -> None:
        async with self._lock:
            self._ws = ws

    async def detach(self) -> None:
        async with self._lock:
            self._ws = None

    async def push(self, event_type: str, payload: dict[str, Any]) -> None:
        message = {"type": event_type, **payload}
        if self._ws is not None:
            try:
                await self._ws.send_json(message)
                return
            except Exception as e:  # noqa: BLE001
                logger.warning("send_json failed, buffering: %s", e)
                await self.detach()
        # buffer for later
        self._pending.append(message)

    async def flush_pending(self) -> None:
        """Send all buffered events to the current connection (used on resync)."""
        if self._ws is None:
            return
        while self._pending:
            msg = self._pending.popleft()
            try:
                await self._ws.send_json(msg)
            except Exception as e:  # noqa: BLE001
                logger.warning("flush failed, re-buffering: %s", e)
                self._pending.appendleft(msg)
                await self.detach()
                return

    async def process_message(
        self,
        msg: dict[str, Any],
        agent: Any,
    ) -> None:
        """Dispatch an incoming client message."""
        msg_type = msg.get("type")
        if msg_type == "decision_intent":
            await self._handle_decision_intent(msg, agent)
        elif msg_type == "decision_draft":
            await self._handle_decision_draft(msg, agent)
        elif msg_type == "user_say":
            text = msg.get("text", "")
            await self.push("agent_say", {"text": f"我听到你说：{text}"})
        elif msg_type == "resync":
            await self.flush_pending()
        elif msg_type == "ping":
            return
        else:
            logger.warning("unknown ws message type: %r", msg_type)

    async def _handle_decision_intent(self, msg: dict, agent: Any) -> None:
        thread_id = msg.get("thread_id")
        intent = msg.get("intent")
        if not thread_id or intent not in ("reply", "archive", "skip"):
            await self.push("error", {"code": "bad_decision_intent", "message": str(msg)})
            return
        config = {"configurable": {"thread_id": thread_id}}
        await agent.aupdate_state(config, {"current_intent": intent})
        await agent.ainvoke(None, config)

    async def _handle_decision_draft(self, msg: dict, agent: Any) -> None:
        thread_id = msg.get("thread_id")
        decision = msg.get("decision")
        feedback = msg.get("feedback")
        if not thread_id or decision not in ("approve", "modify", "reject"):
            await self.push("error", {"code": "bad_decision_draft", "message": str(msg)})
            return
        update: dict[str, Any] = {"draft_decision": decision}
        if decision == "modify" and feedback:
            update["user_feedback"] = feedback
        config = {"configurable": {"thread_id": thread_id}}
        await agent.aupdate_state(config, update)
        await agent.ainvoke(None, config)


def make_app(manager: ConnectionManager, agent_provider: Callable[[], Any]) -> FastAPI:
    """Build a FastAPI app with the /ws endpoint wired to the given manager.

    `agent_provider` is a callable returning the compiled agent — accepts late binding
    so main.py can hand over a not-yet-built agent at startup time.
    """
    app = FastAPI()

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        await manager.attach(ws)
        # On connect, immediately flush any buffered events.
        await manager.flush_pending()
        try:
            while True:
                msg = await ws.receive_json()
                agent = agent_provider()
                await manager.process_message(msg, agent)
        except WebSocketDisconnect:
            pass
        except Exception as e:  # noqa: BLE001
            logger.warning("ws handler error: %s", e)
        finally:
            await manager.detach()

    return app
