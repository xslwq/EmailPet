import { useState } from 'react'
import type { ChatMessage } from '../store/chat'

interface BubbleProps {
  message: ChatMessage
  onFullText: (email: any) => void
  onIntent: (threadId: string, intent: 'reply' | 'archive' | 'skip') => void
  onDraftDecision: (
    threadId: string,
    decision: 'approve' | 'modify' | 'reject',
    feedback?: string,
  ) => void
}

const styles = {
  bubble: {
    margin: '8px 0',
    padding: '12px 14px',
    borderRadius: '14px',
    background: '#fff',
    boxShadow: '0 1px 4px rgba(0,0,0,0.08)',
    fontSize: '13px',
    lineHeight: 1.5,
    color: '#222',
    maxWidth: '95%',
  } as React.CSSProperties,
  small: { fontSize: '11px', color: '#666', marginBottom: '4px' } as React.CSSProperties,
  buttonRow: { display: 'flex', gap: '6px', marginTop: '8px', flexWrap: 'wrap' } as React.CSSProperties,
  btn: {
    padding: '4px 10px',
    border: '1px solid #ccc',
    borderRadius: '8px',
    background: '#f5f5f5',
    cursor: 'pointer',
    fontSize: '12px',
  } as React.CSSProperties,
  primary: {
    background: '#4f7cff',
    color: '#fff',
    borderColor: '#4f7cff',
  } as React.CSSProperties,
  danger: {
    background: '#ffe5e5',
    color: '#a00',
    borderColor: '#f7baba',
  } as React.CSSProperties,
  feedbackInput: {
    width: '100%',
    marginTop: '6px',
    padding: '4px 6px',
    border: '1px solid #ccc',
    borderRadius: '6px',
    fontSize: '12px',
  } as React.CSSProperties,
  errorBubble: {
    background: '#fff3f3',
    border: '1px solid #f7baba',
    color: '#a00',
  } as React.CSSProperties,
  sentBubble: {
    background: '#eafce8',
    border: '1px solid #b6e2ad',
    color: '#1c6e0c',
  } as React.CSSProperties,
}

export function Bubble({ message, onFullText, onIntent, onDraftDecision }: BubbleProps) {
  const p = message.payload
  switch (p.kind) {
    case 'summary':
      return <SummaryBubble payload={p} onFullText={onFullText} onIntent={onIntent} />
    case 'draft':
      return <DraftBubble payload={p} onDecision={onDraftDecision} />
    case 'sent':
      return (
        <div style={{ ...styles.bubble, ...styles.sentBubble }}>
          ✓ 已发送回复（thread {p.threadId}）
        </div>
      )
    case 'agent_say':
      return <div style={styles.bubble}>{p.text}</div>
    case 'error':
      return (
        <div style={{ ...styles.bubble, ...styles.errorBubble }}>
          错误（{p.code}）：{p.message}
        </div>
      )
  }
}

function SummaryBubble({
  payload,
  onFullText,
  onIntent,
}: {
  payload: Extract<ChatMessage['payload'], { kind: 'summary' }>
  onFullText: (email: any) => void
  onIntent: (threadId: string, intent: 'reply' | 'archive' | 'skip') => void
}) {
  return (
    <div style={styles.bubble}>
      <div style={styles.small}>
        来自 {payload.email.from_name} &lt;{payload.email.from_address}&gt;
      </div>
      <div style={styles.small}>主题：{payload.email.subject}</div>
      <div>{payload.summary}</div>
      <div style={styles.buttonRow}>
        <button style={styles.btn} onClick={() => onFullText(payload.email)}>
          看全文
        </button>
        <button
          style={{ ...styles.btn, ...styles.primary }}
          onClick={() => onIntent(payload.threadId, 'reply')}
        >
          写回复
        </button>
        <button style={styles.btn} onClick={() => onIntent(payload.threadId, 'archive')}>
          归档
        </button>
        <button style={styles.btn} onClick={() => onIntent(payload.threadId, 'skip')}>
          跳过
        </button>
      </div>
    </div>
  )
}

function DraftBubble({
  payload,
  onDecision,
}: {
  payload: Extract<ChatMessage['payload'], { kind: 'draft' }>
  onDecision: (
    threadId: string,
    decision: 'approve' | 'modify' | 'reject',
    feedback?: string,
  ) => void
}) {
  const [showFeedback, setShowFeedback] = useState(false)
  const [feedback, setFeedback] = useState('')

  return (
    <div style={styles.bubble}>
      <div style={styles.small}>草稿（{payload.reason}）</div>
      <div style={{ whiteSpace: 'pre-wrap' }}>{payload.draft}</div>
      <div style={styles.buttonRow}>
        <button
          style={{ ...styles.btn, ...styles.primary }}
          onClick={() => onDecision(payload.threadId, 'approve')}
        >
          同意发送
        </button>
        <button
          style={styles.btn}
          onClick={() => setShowFeedback((v) => !v)}
        >
          修改
        </button>
        <button
          style={{ ...styles.btn, ...styles.danger }}
          onClick={() => onDecision(payload.threadId, 'reject')}
        >
          不发了
        </button>
      </div>
      {showFeedback && (
        <div>
          <input
            style={styles.feedbackInput}
            type="text"
            placeholder="想怎么改？例：语气客气一点"
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && feedback.trim()) {
                onDecision(payload.threadId, 'modify', feedback.trim())
                setFeedback('')
                setShowFeedback(false)
              }
            }}
          />
        </div>
      )}
    </div>
  )
}
