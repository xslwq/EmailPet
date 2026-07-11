/**
 * 桌宠动画组件
 * 职责：根据状态显示不同的 emoji 和动画（idle/thinking/speaking）
 */

/** Pet 组件属性 */
interface PetProps {
  state: 'idle' | 'thinking' | 'speaking'
  onClick?: () => void
}

/** 状态对应的 emoji */
const emojiByState: Record<PetProps['state'], string> = {
  idle: '🐱',
  thinking: '🤔',
  speaking: '😺',
}

const styles = {
  wrapper: {
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    height: '80px',
    cursor: 'pointer',
    userSelect: 'none',
  } as React.CSSProperties,
  emoji: {
    fontSize: '48px',
    lineHeight: 1,
    transition: 'transform 0.2s ease',
  } as React.CSSProperties,
}

/**
 * 桌宠组件
 * @param state - 桌宠状态
 * @param onClick - 点击回调
 */
export function Pet({ state, onClick }: PetProps) {
  // 根据状态选择动画：思考时弹跳，说话时缩放
  const animation =
    state === 'thinking'
      ? 'pet-bounce 0.9s ease-in-out infinite'
      : state === 'speaking'
        ? 'pet-talk 0.4s ease-in-out infinite'
        : 'none'

  return (
    <>
      <style>{`
        @keyframes pet-bounce {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-6px); }
        }
        @keyframes pet-talk {
          0%, 100% { transform: scale(1); }
          50% { transform: scale(1.08); }
        }
      `}</style>
      <div style={styles.wrapper} onClick={onClick}>
        <div style={{ ...styles.emoji, animation }}>{emojiByState[state]}</div>
      </div>
    </>
  )
}
