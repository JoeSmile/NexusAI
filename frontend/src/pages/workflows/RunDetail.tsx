import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { formatApiError } from '@/api/http'
import {
  getRun,
  getRunNodes,
  type EvidenceItem,
  type RunNode,
  type WorkflowRun,
} from '@/api/workflowRuns'
import { ForbiddenBanner } from '@/components/role/RoleSwitcher'
import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'

const TERMINAL = new Set(['succeeded', 'failed', 'cancelled'])

function formatOutput(output: unknown): string | null {
  if (output == null) return null
  if (typeof output === 'string') return output
  if (typeof output !== 'object') return String(output)
  const rec = output as Record<string, unknown>
  const result = rec.result
  if (result && typeof result === 'object') {
    const r = result as Record<string, unknown>
    if (typeof r.answer === 'string' && r.answer.trim()) return r.answer
  }
  try {
    return JSON.stringify(output, null, 2)
  } catch {
    return String(output)
  }
}

function formatDuration(start?: string | null, end?: string | null): string {
  if (!start || !end) return '—'
  const ms = new Date(end).getTime() - new Date(start).getTime()
  if (!Number.isFinite(ms) || ms < 0) return '—'
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60000)}m${Math.round((ms % 60000) / 1000)}s`
}

export default function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>()
  const [run, setRun] = useState<WorkflowRun | null>(null)
  const [nodes, setNodes] = useState<RunNode[]>([])
  const [err, setErr] = useState('')
  const timer = useRef<number | null>(null)

  const load = useCallback(async () => {
    if (!runId) return
    try {
      const [r, n] = await Promise.all([getRun(runId), getRunNodes(runId)])
      setRun(r)
      setNodes(n.items)
      setErr('')
      return r.status
    } catch (e) {
      setErr(formatApiError(e, 'run'))
      return null
    }
  }, [runId])

  useEffect(() => {
    let cancelled = false
    const tick = async () => {
      const status = await load()
      if (cancelled) return
      if (status && !TERMINAL.has(status)) {
        timer.current = window.setTimeout(() => void tick(), 2000)
      }
    }
    void tick()
    return () => {
      cancelled = true
      if (timer.current) window.clearTimeout(timer.current)
    }
  }, [load])

  return (
    <div className="space-y-4 p-4">
      <ForbiddenBanner />
      <div className="text-sm">
        <Link className="underline" to="/runs">
          ← 运行历史
        </Link>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>运行详情</CardTitle>
          <CardDescription>
            {run ? (
              <>
                {run.workflow_name || run.workflow_id} ·{' '}
                <Badge>{run.status}</Badge>
                {run.error_message ? (
                  <span className="ml-2 text-destructive">{run.error_message}</span>
                ) : null}
                {run.status === 'suspended' && run.hang_summary ? (
                  <span className="ml-2 text-amber-700 dark:text-amber-400">
                    {run.hang_summary}
                  </span>
                ) : null}
              </>
            ) : (
              '加载中…'
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {err ? <p className="text-sm text-destructive">{err}</p> : null}
          {nodes.length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无节点输出。</p>
          ) : (
            nodes.map((n) => {
              const outText = formatOutput(n.output)
              return (
              <div key={n.id} className="rounded-md border p-3 space-y-2">
                <div className="flex items-center gap-2 text-sm">
                  <span className="font-medium">{n.node_id}</span>
                  <Badge variant="secondary">{n.status}</Badge>
                  <span className="text-xs text-muted-foreground">
                    {formatDuration(n.started_at, n.finished_at)}
                  </span>
                  {n.error_message ? (
                    <span className="text-destructive">{n.error_message}</span>
                  ) : null}
                </div>
                <div className="space-y-1">
                  <p className="text-xs text-muted-foreground">Evidence</p>
                  {(n.evidence || []).length === 0 ? (
                    <p className="text-xs text-muted-foreground">[]</p>
                  ) : (
                    (n.evidence || []).map((e: EvidenceItem, i: number) => (
                      <div key={i} className="text-sm">
                        {/* text nodes — React escapes; no dangerouslySetInnerHTML */}
                        <div className="font-medium">{e.title}</div>
                        {e.snippet ? (
                          <div className="text-muted-foreground whitespace-pre-wrap">
                            {e.snippet}
                          </div>
                        ) : null}
                      </div>
                    ))
                  )}
                </div>
                {outText ? (
                  <div className="space-y-1">
                    <p className="text-xs text-muted-foreground">输出</p>
                    <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-sm">
                      {outText}
                    </pre>
                  </div>
                ) : null}
              </div>
              )
            })
          )}
        </CardContent>
      </Card>
    </div>
  )
}
