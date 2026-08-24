/** Clarification card — Task 65 slice 6 SSE clarify event UI. */
import type { ClarificationInfo } from '@/hooks/useChatStream'

type Props = {
  info: ClarificationInfo
  disabled?: boolean
  onPick?: (text: string) => void
}

export function ClarificationCard({ info, disabled, onPick }: Props) {
  const options = Array.isArray(info.options) ? info.options : []
  return (
    <div className="clarification-card" style={{ marginTop: 10 }}>
      <div
        className="clarification-card__hint"
        style={{ fontSize: 13, color: 'var(--text-secondary, #666)', marginBottom: 8 }}
      >
        需要您补充信息后才能继续
      </div>
      {options.length > 0 ? (
        <div className="clarification-card__options" style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {options.map((opt) => (
            <button
              key={opt}
              type="button"
              className="nav-tab"
              disabled={disabled}
              onClick={() => onPick?.(opt)}
            >
              {opt}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}
