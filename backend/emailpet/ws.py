"""WebSocket routing and connection management for EmailPet.
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


# 离线消息缓冲队列最大长度：超过则丢弃旧消息
PENDING_QUEUE_MAX = 50


class ConnectionManager:
    """WebSocket 连接管理器（单连接设计）+ 消息路由。

    发送端：Agent 节点调用 `push(event_type, payload)`。若客户端已连接则立即发送；
           否则缓冲最多 PENDING_QUEUE_MAX 条消息，等待重连后通过 `resync` 投递。

    接收端：`process_message(msg, agent)` 根据 `type` 字段路由到对应处理器。

    设计约束：同时只允许一个前端连接，新连接会踢掉旧连接。
    """

    def __init__(self) -> None:
        self._ws: Optional[WebSocket] = None                     # 当前活动连接
        self._pending: deque[dict[str, Any]] = deque(maxlen=PENDING_QUEUE_MAX)  # 离线消息缓冲
        self._lock = asyncio.Lock()                              # 保护连接状态的锁

    @property
    def connected(self) -> bool:
        """是否有活跃的 WebSocket 连接。"""
        return self._ws is not None

    async def attach(self, ws: WebSocket) -> None:
        """绑定新的 WebSocket 连接（单连接：会替换旧连接）。"""
        async with self._lock:
            self._ws = ws

    async def detach(self) -> None:
        """解绑当前 WebSocket 连接。"""
        async with self._lock:
            self._ws = None

    async def push(self, event_type: str, payload: dict[str, Any]) -> None:
        """推送事件到前端，离线时缓冲。

        参数：
            event_type: 事件类型标识
            payload: 事件数据字典
        """
        message = {"type": event_type, **payload}
        if self._ws is not None:
            try:
                await self._ws.send_json(message)
                return
            except Exception as e:  # noqa: BLE001
                logger.warning("send_json failed, buffering: %s", e)
                await self.detach()
        # 发送失败或离线时，加入缓冲队列等待重连
        self._pending.append(message)

    async def flush_pending(self) -> None:
        """将所有缓冲的离线消息发送给当前连接（重连时调用）。

        若发送中途失败，将剩余消息放回缓冲队列并断开连接。
        """
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
        free_chat_agent: Any,
    ) -> None:
        """处理前端发来的消息，根据 type 字段路由。

        参数：
            msg: 消息字典，必须包含 type 字段
            agent: LangGraph Agent 实例（邮件处理），用于恢复执行
            free_chat_agent: LangGraph Agent 实例（自由对话）
        """
        msg_type = msg.get("type")
        if msg_type == "decision_intent":
            await self._handle_decision_intent(msg, agent)
        elif msg_type == "decision_draft":
            await self._handle_decision_draft(msg, agent)
        elif msg_type == "user_say":
            text = msg.get("text", "")
            await self._handle_user_say(text, free_chat_agent)
        elif msg_type == "resync":
            await self.flush_pending()
        elif msg_type == "ping":
            return
        else:
            logger.warning("unknown ws message type: %r", msg_type)

    async def _handle_user_say(self, text: str, free_chat_agent: Any) -> None:
        """路由 user_say 到 free_chat agent。

        首次：ainvoke({"messages":[user_msg]}, config)
        后续：aupdate_state({"messages":[user_msg]}, config) + ainvoke(None, config) resume

        参数：
            text: 用户输入文本
            free_chat_agent: free_chat LangGraph Agent 实例
        """
        if free_chat_agent is None:
            # embedding 未配置，free_chat 不可用
            await self.push("agent_say", {"text": "（未配置 embedding，自由对话不可用）"})
            return
        config = {"configurable": {"thread_id": "chat_default"}}
        new_msg = {"role": "user", "content": text}
        try:
            # 尝试后续：thread 已存在，update + resume
            await free_chat_agent.aupdate_state(config, {"messages": [new_msg]})
            await free_chat_agent.ainvoke(None, config)
        except Exception:
            # 首次：thread 不存在，ainvoke(initial_state)
            await free_chat_agent.ainvoke({"messages": [new_msg]}, config)

    async def _handle_decision_intent(self, msg: dict, agent: Any) -> None:
        """处理 intent 决策（在意图中断点 resume）。

        区别：在用户选择"回复/归档/跳过"时调用，更新 current_intent 后继续执行。

        参数：
            msg: 包含 thread_id 和 intent 的消息
            agent: LangGraph Agent 实例
        """
        thread_id = msg.get("thread_id")
        intent = msg.get("intent")
        if not thread_id or intent not in ("reply", "archive", "skip"):
            await self.push("error", {"code": "bad_decision_intent", "message": str(msg)})
            return
        config = {"configurable": {"thread_id": thread_id}}
        # 先更新状态，注入用户意图
        await agent.aupdate_state(config, {"current_intent": intent})
        # 再从断点继续执行 Agent
        await agent.ainvoke(None, config)

    async def _handle_decision_draft(self, msg: dict, agent: Any) -> None:
        """处理草稿决策（在草稿中断点 resume）。

        区别：在用户选择"批准/修改/拒绝"草稿回复时调用，可附带修改意见。

        参数：
            msg: 包含 thread_id、decision 和可选 feedback 的消息
            agent: LangGraph Agent 实例
        """
        thread_id = msg.get("thread_id")
        decision = msg.get("decision")
        feedback = msg.get("feedback")
        if not thread_id or decision not in ("approve", "modify", "reject"):
            await self.push("error", {"code": "bad_decision_draft", "message": str(msg)})
            return
        update: dict[str, Any] = {"draft_decision": decision}
        # 修改时需要传入用户反馈
        if decision == "modify" and feedback:
            update["user_feedback"] = feedback
        config = {"configurable": {"thread_id": thread_id}}
        # 先更新状态，注入用户决策
        await agent.aupdate_state(config, update)
        # 再从断点继续执行 Agent
        await agent.ainvoke(None, config)


def make_app(
    manager: ConnectionManager,
    agent_provider: Callable[[], Any],
    free_chat_agent_provider: Callable[[], Any],
) -> FastAPI:
    """构建带 /ws 端点的 FastAPI 应用。

    参数：
        manager: ConnectionManager 实例
        agent_provider: 延迟绑定的 Agent 工厂函数（邮件处理），
                       让 main.py 可以在启动阶段传入尚未构建完成的 Agent
        free_chat_agent_provider: 延迟绑定的 Agent 工厂函数（自由对话）

    返回：
        配置好 WebSocket 端点的 FastAPI 应用
    """
    app = FastAPI()

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        await manager.attach(ws)
        # 连接建立后立即投递离线缓冲消息
        await manager.flush_pending()
        try:
            while True:
                msg = await ws.receive_json()
                agent = agent_provider()
                free_chat_agent = free_chat_agent_provider()
                await manager.process_message(msg, agent, free_chat_agent)
        except WebSocketDisconnect:
            pass
        except Exception as e:  # noqa: BLE001
            logger.warning("ws handler error: %s", e)
        finally:
            await manager.detach()

    return app
