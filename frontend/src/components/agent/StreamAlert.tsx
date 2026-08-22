import { AlertTriangle, Info, ShieldAlert, WifiOff, XCircle } from 'lucide-react'

import type { StreamAlert } from '@/hooks/sseParse'

type Props = {
  alert: StreamAlert | null
  onDismiss?: () => void
}

const STYLES: Record<
  StreamAlert['kind'],
  { className: string; icon: typeof Info }
> = {
  error: {
    className: 'border-red-200 bg-red-50 text-red-900',
    icon: XCircle,
  },
  guardrail: {
    className: 'border-amber-200 bg-amber-50 text-amber-950',
    icon: ShieldAlert,
  },
  retraction: {
    className: 'border-orange-200 bg-orange-50 text-orange-950',
    icon: AlertTriangle,
  },
  reconnect: {
    className: 'border-blue-200 bg-blue-50 text-blue-950',
    icon: WifiOff,
  },
  cancelled: {
    className: 'border-slate-200 bg-slate-50 text-slate-800',
    icon: Info,
  },
  info: {
    className: 'border-slate-200 bg-slate-50 text-slate-800',
    icon: Info,
  },
}

export function StreamAlertBanner({ alert, onDismiss }: Props) {
  if (!alert) return null
  const style = STYLES[alert.kind]
  const Icon = style.icon
  return (
    <div
      className={`mb-2 flex items-start gap-2 rounded-lg border px-3 py-2 text-sm ${style.className}`}
      role="alert"
      data-testid={`stream-alert-${alert.kind}`}
    >
      <Icon size={16} className="mt-0.5 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        {alert.title ? <div className="font-medium">{alert.title}</div> : null}
        <div>{alert.message}</div>
        {alert.code ? (
          <div className="mt-0.5 font-mono text-xs opacity-70">{alert.code}</div>
        ) : null}
      </div>
      {onDismiss ? (
        <button
          type="button"
          className="shrink-0 text-xs underline opacity-80"
          onClick={onDismiss}
        >
          关闭
        </button>
      ) : null}
    </div>
  )
}
