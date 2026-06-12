interface EmailFull {
  from_name: string
  from_address: string
  subject: string
  received_at: string
  body_text: string
}

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

export function FullTextModal({ visible, email, onClose }: FullTextModalProps) {
  if (!visible || !email) return null
  return (
    <div style={styles.overlay} onClick={onClose}>
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
