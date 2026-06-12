import { create } from 'zustand'

// Backend event types we render in the chat
export type SummaryMessage = {
  kind: 'summary'
  threadId: string
  email: { from_name: string; from_address: string; subject: string; received_at: string }
  summary: string
  bodyText: string
  suggestedAction: string
}

export type DraftMessage = {
  kind: 'draft'
  threadId: string
  draft: string
  reason: string
}

export type SentMessage = {
  kind: 'sent'
  threadId: string
  emailId: string
}

export type AgentSayMessage = {
  kind: 'agent_say'
  text: string
}

export type ErrorMessage = {
  kind: 'error'
  code: string
  message: string
}

export type ChatPayload =
  | SummaryMessage
  | DraftMessage
  | SentMessage
  | AgentSayMessage
  | ErrorMessage

export interface ChatMessage {
  id: string
  ts: number
  payload: ChatPayload
}

interface ChatState {
  messages: ChatMessage[]
  add: (payload: ChatPayload) => void
  clear: () => void
}

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
