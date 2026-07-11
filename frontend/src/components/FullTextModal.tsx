/**
 * 邮件全文弹窗组件
 * 职责：显示完整邮件内容的模态框
 */

/** 完整邮件数据结构 */
interface EmailFull {
  from_name: string
  from_address: string
  subject: string
  received_at: string
  body_text: string
}

/** FullTextModal 组件属性 */
interface FullTextModalProps {
  visible: boolean
  email: EmailFull | null
  onClose: () => void
}

const styles = {
  overlay: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0,0,0,0.45)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000,
  } as React.CSSProperties,
  modal: {
    background: '#fff',
    width: 'min(90vw, 520px)',
    maxHeight: '80vh',
    display: 'flex',
    flexDirection: 'column',
    borderRadius: '12px',
    overflow: 'hidden',
    boxShadow: '0 4px 24px rgba(0,0,0,0.2)',
  } as React.CSSProperties,
  header: {
    padding: '12px 14px',
    borderBottom: '1px solid #eee',
    display: 'flex',
    flexDirection: 'column',
    gap: '4px',
    fontSize: '12px',
    color: '#444',
  } as React.CSSProperties,
  closeBtn: {
    position: 'absolute',
    top: '8px',
    right: '10px',
    background: 'transparent',
    border: 'none',
    fontSize: '18px',
    cursor: 'pointer',
    color: '#888',
  } as React.CSSProperties,
  body: {
    padding: '12px 14px',
    overflow: 'auto',
    fontSize: '13px',
    lineHeight: 1.6,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    color: '#222',
  } as React.CSSProperties,
}

/**
 * 邮件全文弹窗组件
 * @param visible - 是否显示
 * @param email - 邮件数据
 * @param onClose - 关闭回调
 */
export function FullTextModal({ visible, email, onClose }: FullTextModalProps) {
  if (!visible || !email) return null
  return (
    <div style={styles.overlay} onClick={onClose}>
      {/* 点击遮罩层关闭，点击弹窗内部不关闭 */}
      <div style={{ position: 'relative', ...styles.modal }} onClick={(e) => e.stopPropagation()}>
        <button style={styles.closeBtn} onClick={onClose} aria-label="关闭">
          ✕
        </button>
        <div style={styles.header}>
          <div>
            <strong>发件人：</strong>
            {email.from_name} &lt;{email.from_address}&gt;
          </div>
          <div>
            <strong>主题：</strong>
            {email.subject}
          </div>
          <div>
            <strong>时间：</strong>
            {email.received_at}
          </div>
        </div>
        <div style={styles.body}>{email.body_text}</div>
      </div>
    </div>
  )
}
