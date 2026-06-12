interface PetProps {
  state: 'idle' | 'thinking' | 'speaking'
  onClick?: () => void
}

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

export function Pet({ state, onClick }: PetProps) {
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
