/**
 * 用户输入框组件
 * 职责：接收用户文本输入，支持回车发送
 */
import { useState } from 'react'

/** Input 组件属性 */
interface InputProps {
  onSend: (text: string) => void
  disabled?: boolean
  placeholder?: string
}

const styles = {
  container: {
    display: 'flex',
    gap: '6px',
    padding: '10px',
    background: '#fafafa',
    borderTop: '1px solid #e0e0e0',
  } as React.CSSProperties,
  input: {
    flex: 1,
    padding: '8px 10px',
    border: '1px solid #ccc',
    borderRadius: '8px',
    fontSize: '13px',
    outline: 'none',
  } as React.CSSProperties,
  button: {
    padding: '8px 14px',
    border: 'none',
    borderRadius: '8px',
    background: '#4f7cff',
    color: '#fff',
    fontSize: '13px',
    cursor: 'pointer',
  } as React.CSSProperties,
  buttonDisabled: {
    background: '#aab',
    cursor: 'not-allowed',
  } as React.CSSProperties,
}

/**
 * 输入框组件
 * @param onSend - 发送回调
 * @param disabled - 是否禁用
 * @param placeholder - 占位文本
 */
export function Input({ onSend, disabled = false, placeholder = '说点什么…' }: InputProps) {
  const [text, setText] = useState('')

  /** 提交输入内容 */
  const submit = () => {
    const trimmed = text.trim()
    if (!trimmed) return
    onSend(trimmed)
    setText('')
  }

  const isSendDisabled = disabled || !text.trim()

  return (
    <div style={styles.container}>
      <input
        type="text"
        style={styles.input}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            submit()
          }
        }}
      />
      <button
        style={{
          ...styles.button,
          ...(isSendDisabled ? styles.buttonDisabled : {}),
        }}
        onClick={submit}
        disabled={isSendDisabled}
      >
        发送
      </button>
    </div>
  )
}
