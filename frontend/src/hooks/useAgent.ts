/**
 * WebSocket 连接 Hook
 * 职责：管理与后端的 WebSocket 连接、自动重连、消息收发
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useChatStore, type ChatPayload } from '../store/chat'

/** WebSocket 服务地址 */
const WS_URL = 'ws://127.0.0.1:8765/ws'
/** 重连延迟（毫秒） */
const RECONNECT_DELAY_MS = 2000

/** 后端发来的 WebSocket 消息类型 */
type ServerMessage =
  | {
      type: 'summary'
      thread_id: string
      email: {
        from_name: string
        from_address: string
        subject: string
        received_at: string
      }
      summary: string
      body_text: string
      suggested_action: string
    }
  | { type: 'draft'; thread_id: string; draft: string; reason: string }
  | { type: 'sent'; thread_id: string; email_id: string }
  | { type: 'agent_say'; text: string }
  | { type: 'error'; code: string; message: string }

/**
 * 将后端消息转换为前端 Payload 格式
 * @param msg - 后端消息
 * @returns 前端 Payload 或 null（未知类型）
 */
function toPayload(msg: ServerMessage): ChatPayload | null {
  switch (msg.type) {
    case 'summary':
      return {
        kind: 'summary',
        threadId: msg.thread_id,
        email: msg.email,
        summary: msg.summary,
        bodyText: msg.body_text,
        suggestedAction: msg.suggested_action,
      }
    case 'draft':
      return {
        kind: 'draft',
        threadId: msg.thread_id,
        draft: msg.draft,
        reason: msg.reason,
      }
    case 'sent':
      return { kind: 'sent', threadId: msg.thread_id, emailId: msg.email_id }
    case 'agent_say':
      return { kind: 'agent_say', text: msg.text }
    case 'error':
      return { kind: 'error', code: msg.code, message: msg.message }
    default:
      return null
  }
}

/**
 * Agent WebSocket Hook
 * @returns 连接状态、消息列表、发送方法
 */
export function useAgent() {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<number | null>(null)
  const [connected, setConnected] = useState(false)
  const messages = useChatStore((s) => s.messages)
  const add = useChatStore((s) => s.add)

  /** 建立 WebSocket 连接 */
  const connect = useCallback(() => {
    const ws = new WebSocket(WS_URL)
    wsRef.current = ws
    ws.onopen = () => {
      setConnected(true)
      ws.send(JSON.stringify({ type: 'resync' })) // 请求同步历史消息
    }
    ws.onmessage = (e) => {
      try {
        const msg: ServerMessage = JSON.parse(e.data)
        const payload = toPayload(msg)
        if (payload) add(payload)
      } catch (err) {
        console.error('failed to parse ws message', err, e.data)
      }
    }
    ws.onclose = () => {
      setConnected(false)
      wsRef.current = null
      reconnectTimerRef.current = window.setTimeout(connect, RECONNECT_DELAY_MS)
    }
    ws.onerror = (err) => {
      console.warn('ws error', err)
    }
  }, [add])

  // 组件挂载时连接，卸载时清理
  useEffect(() => {
    connect()
    return () => {
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      wsRef.current?.close()
    }
  }, [connect])

  /** 发送消息到后端 */
  const send = useCallback((msg: object) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg))
    } else {
      console.warn('ws not open, dropping message', msg)
    }
  }, [])

  /** 发送邮件处理意图 */
  const sendIntent = useCallback(
    (threadId: string, intent: 'reply' | 'archive' | 'skip') => {
      send({ type: 'decision_intent', thread_id: threadId, intent })
    },
    [send],
  )

  /** 发送草稿决定 */
  const sendDraftDecision = useCallback(
    (
      threadId: string,
      decision: 'approve' | 'modify' | 'reject',
      feedback?: string,
    ) => {
      send({ type: 'decision_draft', thread_id: threadId, decision, feedback })
    },
    [send],
  )

  /** 发送用户聊天消息 */
  const sendUserSay = useCallback(
    (text: string) => {
      send({ type: 'user_say', text })
    },
    [send],
  )

  return {
    connected,
    messages,
    sendIntent,
    sendDraftDecision,
    sendUserSay,
  }
}
