import type { AuditNdjsonEvent } from '@/api/audit'

type Props = {
  events: AuditNdjsonEvent[]
}

const TYPE_LABEL: Record<string, string> = {
  turn_begin: '对话开始',
  tool_call: '工具调用',
  tool_result: '工具结果',
  audit_event: '审计事件',
}

function eventLabel(ev: AuditNdjsonEvent): string {
  if (ev.action) return ev.action
  return TYPE_LABEL[ev.type] || ev.type
}

function eventDetail(ev: AuditNdjsonEvent): string {
  if (ev.decision_explain) {
    try {
      const parsed = JSON.parse(ev.decision_explain) as { reason?: string; stages?: unknown[] }
      if (parsed.reason) return `治理: ${parsed.reason}`
    } catch {
      return ev.decision_explain.slice(0, 240)
    }
  }
  if (ev.error_code) return `错误: ${ev.error_code}`
  if (ev.output_preview) return ev.output_preview.slice(0, 240)
  if (ev.output_text) return ev.output_text.slice(0, 240)
  if (ev.input_preview) return ev.input_preview.slice(0, 240)
  if (ev.model) return ev.model
  return '—'
}

export function TraceTimeline({ events }: Props) {
  if (!events.length) {
    return <p className="text-muted-foreground text-xs">无链路事件</p>
  }

  return (
    <ol className="space-y-2 border-l border-border pl-3">
      {events.map((ev, idx) => {
        const failed = Boolean(ev.error_code)
        return (
          <li key={`${ev.type}-${ev.ts}-${idx}`} className="relative text-xs">
            <span
              className={`absolute -left-[1.35rem] top-1 h-2 w-2 rounded-full ${
                failed ? 'bg-red-500' : 'bg-emerald-500'
              }`}
            />
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{eventLabel(ev)}</span>
              <span className="text-muted-foreground">{ev.ts || '—'}</span>
              {ev.latency_ms != null ? (
                <span className="text-muted-foreground">{ev.latency_ms}ms</span>
              ) : null}
              {ev.input_tokens != null || ev.output_tokens != null ? (
                <span className="text-muted-foreground">
                  tok {(ev.input_tokens || 0) + (ev.output_tokens || 0)}
                </span>
              ) : null}
            </div>
            <p className={`mt-1 break-all ${failed ? 'text-red-600' : 'text-muted-foreground'}`}>
              {eventDetail(ev)}
            </p>
          </li>
        )
      })}
    </ol>
  )
}
