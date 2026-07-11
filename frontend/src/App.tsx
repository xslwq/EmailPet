/**
 * EmailPet 根组件
 * 职责：整体布局、桌宠动画状态管理、消息列表自动滚动、WebSocket 连接状态显示
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Bubble } from './components/Bubble'
import { FullTextModal } from './components/FullTextModal'
import { Input } from './components/Input'
import { Pet } from './components/Pet'
import { useAgent } from './hooks/useAgent'

/** 邮件全文弹窗数据结构 */
interface FullTextEmail {
  from_name: string
  from_address: string
  subject: string
  received_at: string
  body_text: string
}

const styles = {
  root: {
    width: '100vw',
    height: '100vh',
    display: 'flex',
    flexDirection: 'column',
    background: 'rgba(255, 255, 255, 0.92)',
    borderRadius: '16px',
    overflow: 'hidden',
    fontFamily: '"Microsoft YaHei", "Noto Sans CJK SC", "PingFang SC", system-ui, -apple-system, sans-serif',
    boxShadow: '0 6px 24px rgba(0, 0, 0, 0.18)',
    position: 'relative',
  } as React.CSSProperties,
  header: {
    flex: '0 0 auto',
    padding: '8px 0',
    borderBottom: '1px solid #eee',
    cursor: 'move',
    userSelect: 'none',
    background: 'rgba(255,255,255,0.6)',
    WebkitAppRegion: 'drag', // Electron 拖拽区域标记
  } as React.CSSProperties,
  scroll: {
    flex: 1,
    overflowY: 'auto',
    padding: '6px 10px',
    background: '#f7f8fa',
  } as React.CSSProperties,
  empty: {
    color: '#999',
    fontSize: '12px',
    textAlign: 'center',
    padding: '40px 12px',
  } as React.CSSProperties,
  status: {
    position: 'absolute',
    top: 6,
    right: 10,
    fontSize: '10px',
    padding: '2px 6px',
    borderRadius: '4px',
    color: '#fff',
  } as React.CSSProperties,
  statusOnline: { background: '#4caf50' } as React.CSSProperties,
  statusOffline: { background: '#bbb' } as React.CSSProperties,
}

export default function App() {
  const { connected, messages, sendIntent, sendDraftDecision, sendUserSay } =
    useAgent()
  const [fullTextEmail, setFullTextEmail] = useState<FullTextEmail | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)

  // 新消息到达时自动滚动到底部
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  // 桌宠状态：新消息后1.5秒内显示"speaking"，之后恢复"idle"
  const lastTs = messages.length > 0 ? messages[messages.length - 1].ts : 0
  const [petState, setPetState] = useState<'idle' | 'thinking' | 'speaking'>(
    'idle',
  )
  useEffect(() => {
    if (lastTs === 0) return
    setPetState('speaking')
    const t = window.setTimeout(() => setPetState('idle'), 1500)
    return () => window.clearTimeout(t)
  }, [lastTs])

  const renderedMessages = useMemo(
    () =>
      messages.map((m) => (
        <Bubble
          key={m.id}
          message={m}
          onFullText={(email) => setFullTextEmail(email)}
          onIntent={sendIntent}
          onDraftDecision={sendDraftDecision}
        />
      )),
    [messages, sendIntent, sendDraftDecision],
  )

  return (
    <div style={styles.root}>
      <div
        style={{
          ...styles.status,
          ...(connected ? styles.statusOnline : styles.statusOffline),
        }}
      >
        {connected ? '在线' : '离线'}
      </div>

      <div style={styles.header}>
        <Pet state={petState} />
      </div>

      <div ref={scrollRef} style={styles.scroll}>
        {messages.length === 0 ? (
          <div style={styles.empty}>
            {connected
              ? '小猫在替你看着邮箱…有重要邮件会跳出来跟你说话。'
              : '正在连接后端…'}
          </div>
        ) : (
          renderedMessages
        )}
      </div>

      <Input
        onSend={sendUserSay}
        disabled={!connected}
        placeholder="跟小猫说点什么…"
      />

      <FullTextModal
        visible={fullTextEmail !== null}
        email={fullTextEmail}
        onClose={() => setFullTextEmail(null)}
      />
    </div>
  )
}
