import { useEffect, useState } from 'react'

import {
  fetchAuditLogs,
  fetchAuditNdjsonEvents,
  type AuditLogRow,
  type AuditNdjsonEvent,
} from '@/api/audit'
import { fetchRunSnapshot } from '@/api/chat'
import { formatApiError } from '@/api/http'
import { ExecutionPanel } from '@/components/agent/ExecutionPanel'
import { TraceMemorySnapshot } from '@/components/trace/TraceMemorySnapshot'
import { TraceTimeline } from '@/components/trace/TraceTimeline'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { executionFromSnapshot } from '@/hooks/sseParse'
import { parseMemorySnapshotFromAudit } from '@/lib/memorySnapshot'

type Props = {
  traceId: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function TraceDetailDrawer({ traceId, open, onOpenChange }: Props) {
  const [rows, setRows] = useState<AuditLogRow[]>([])
  const [events, setEvents] = useState<AuditNdjsonEvent[]>([])
  const [snapshotGoal, setSnapshotGoal] = useState<string | null>(null)
  const [execution, setExecution] = useState(
    () => executionFromSnapshot(undefined, undefined),
  )
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open || !traceId) return
    let cancelled = false
    const load = async () => {
      setBusy(true)
      setErr('')
      try {
        const [logRows, ndjson, snap] = await Promise.all([
          fetchAuditLogs({ trace_id: traceId, limit: 200 }),
          fetchAuditNdjsonEvents({ trace_id: traceId }).catch(() => [] as AuditNdjsonEvent[]),
          fetchRunSnapshot(traceId).catch(() => null),
        ])
        if (cancelled) return
        setRows(logRows)
        setEvents(ndjson)
        if (snap?.snapshot && typeof snap.snapshot === 'object') {
          const goal = String((snap.snapshot as { goal?: string }).goal || '')
          setSnapshotGoal(goal || null)
          setExecution(executionFromSnapshot(snap.snapshot, traceId))
        } else {
          setSnapshotGoal(null)
          setExecution(null)
        }
      } catch (e) {
        if (!cancelled) {
          setRows([])
          setEvents([])
          setSnapshotGoal(null)
          setExecution(null)
          setErr(formatApiError(e, 'audit:read'))
        }
      } finally {
        if (!cancelled) setBusy(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [open, traceId])

  const memorySnapshot = parseMemorySnapshotFromAudit(events, rows)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>链路详情</DialogTitle>
          <DialogDescription className="font-mono text-xs break-all">
            {traceId || '—'}
          </DialogDescription>
        </DialogHeader>

        {err ? (
          <p className="text-destructive text-sm" role="alert">
            {err}
          </p>
        ) : null}
        {busy ? <p className="text-muted-foreground text-xs">加载中…</p> : null}

        {snapshotGoal ? (
          <p className="text-sm">
            <span className="text-muted-foreground">目标：</span>
            {snapshotGoal}
          </p>
        ) : null}

        <ExecutionPanel execution={execution} />
        {!execution && rows.some((r) => r.action.includes('task_plan')) ? (
          <p className="text-muted-foreground text-xs">
            执行图快照不可用（进程重启后仅保留审计回放）
          </p>
        ) : null}

        <section className="space-y-2">
          <h3 className="text-sm font-semibold">Memory 快照</h3>
          <TraceMemorySnapshot snapshot={memorySnapshot} />
        </section>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold">时序事件</h3>
          <TraceTimeline events={events} />
        </section>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold">审计行 ({rows.length})</h3>
          <ul className="max-h-48 space-y-1 overflow-y-auto text-xs">
            {rows.map((r) => (
              <li key={r.id} className="rounded border border-border/60 px-2 py-1">
                <span className="font-medium">{r.action}</span>
                <span className="text-muted-foreground"> · {r.created_at}</span>
                {r.error_code ? (
                  <span className="text-red-600"> · {r.error_code}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </section>

        <div className="flex justify-end">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            关闭
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
