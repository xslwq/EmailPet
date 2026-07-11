/**
 * 聊天状态 Store（Zustand）
 * 职责：管理聊天消息列表，支持添加/清空消息
 */
import { create } from 'zustand'

/** 邮件摘要消息 */
export type SummaryMessage = {
  kind: 'summary'
  threadId: string
  email: { from_name: string; from_address: string; subject: string; received_at: string }
  summary: string
  bodyText: string
  suggestedAction: string
}

/** 草稿消息 */
export type DraftMessage = {
  kind: 'draft'
  threadId: string
  draft: string
  reason: string
}

/** 已发送消息 */
export type SentMessage = {
  kind: 'sent'
  threadId: string
  emailId: string
}

/** Agent 说话消息 */
export type AgentSayMessage = {
  kind: 'agent_say'
  text: string
}

/** 错误消息 */
export type ErrorMessage = {
  kind: 'error'
  code: string
  message: string
}

/** 聊天消息 Payload 联合类型 */
export type ChatPayload =
  | SummaryMessage
  | DraftMessage
  | SentMessage
  | AgentSayMessage
  | ErrorMessage

/** 聊天消息（带 ID 和时间戳） */
export interface ChatMessage {
  id: string
  ts: number
  payload: ChatPayload
}

/** Chat Store 状态接口 */
interface ChatState {
  messages: ChatMessage[]
  add: (payload: ChatPayload) => void
  clear: () => void
}

/** Chat Store 实例 */
export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  add: (payload) =>
    set((s) => ({
      messages: [
        ...s.messages,
        { id: crypto.randomUUID(), ts: Date.now(), payload },
      ],
    })),
  clear: () => set({ messages: [] }),
}))
