import {
  inputLengthHint,
  isNearInputLimit,
  isOverInputLimit,
  maskSensitivePreview,
  type SensitiveFinding,
} from '@/lib/clientGuardrails'

type Props = {
  input: string
  validationError: string | null
  findings: SensitiveFinding[]
}

export function ClientInputGuardrailBar({
  input,
  validationError,
  findings,
}: Props) {
  const len = input.length
  const masked = findings.length > 0 ? maskSensitivePreview(input) : null
  const showCounter = len > 0 && (isNearInputLimit(len) || findings.length > 0)

  if (!validationError && !showCounter && !masked) return null

  return (
    <div className="px-1 pb-1 text-xs" data-testid="client-input-guardrail">
      {validationError ? (
        <p className="mb-1 text-red-600" role="alert">
          {validationError}
        </p>
      ) : null}
      {showCounter ? (
        <p
          className={
            isOverInputLimit(len)
              ? 'text-red-600 font-medium'
              : isNearInputLimit(len)
                ? 'text-amber-700'
                : 'text-[#64748B]'
          }
        >
          {inputLengthHint(len)}
          {isOverInputLimit(len) ? ' · 已超限，请缩短后再发送' : null}
        </p>
      ) : null}
      {masked && masked !== input ? (
        <p className="mt-1 text-amber-800">
          本地预览（脱敏）：<span className="font-mono">{masked.slice(0, 200)}</span>
          {masked.length > 200 ? '…' : ''}
        </p>
      ) : null}
    </div>
  )
}
