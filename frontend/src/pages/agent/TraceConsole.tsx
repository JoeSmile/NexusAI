import { useEffect, useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'

import {
  fetchAuditLogs,
  groupAuditRowsByTrace,
  type TraceSummary,
} from '@/api/audit'
import { formatApiError } from '@/api/http'
import { TraceDetailDrawer } from '@/components/trace/TraceDetailDrawer'
import { ForbiddenBanner } from '@/components/role/RoleSwitcher'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useAuthStore } from '@/stores/authStore'

const PAGE_SIZE = 20
const FETCH_LIMIT = 500

function sortTracesNewestFirst(items: TraceSummary[]): TraceSummary[] {
  return [...items].sort((a, b) => {
    const ta = Date.parse(a.last_activity_at) || 0
    const tb = Date.parse(b.last_activity_at) || 0
    if (tb !== ta) return tb - ta
    return b.trace_id.localeCompare(a.trace_id)
  })
}

export default function TraceConsole() {
  const [searchParams] = useSearchParams()
  const capabilityFilter = (searchParams.get('capability_id') || '').trim()
  const role = useAuthStore((s) => s.activeRole)
  const roleEpoch = useAuthStore((s) => s.roleEpoch)
  const [traceFilter, setTraceFilter] = useState('')
  const [action, setAction] = useState('')
  const [traces, setTraces] = useState<TraceSummary[]>([])
  const [page, setPage] = useState(1)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [selectedTrace, setSelectedTrace] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  const totalPages = Math.max(1, Math.ceil(traces.length / PAGE_SIZE))
  const pageTraces = useMemo(() => {
    const start = (page - 1) * PAGE_SIZE
    return traces.slice(start, start + PAGE_SIZE)
  }, [traces, page])

  const load = async () => {
    setBusy(true)
    setErr('')
    try {
      const rows = await fetchAuditLogs({
        trace_id: traceFilter.trim() || undefined,
        action: action.trim() || undefined,
        limit: FETCH_LIMIT,
        offset: 0,
      })
      const scoped = capabilityFilter
        ? rows.filter((r) => (r.model || '').trim() === capabilityFilter)
        : rows
      setTraces(sortTracesNewestFirst(groupAuditRowsByTrace(scoped)))
      setPage(1)
    } catch (e) {
      setTraces([])
      setPage(1)
      setErr(formatApiError(e, 'audit:read'))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refresh on role switch
  }, [roleEpoch, role, capabilityFilter])

  useEffect(() => {
    if (page > totalPages) setPage(totalPages)
  }, [page, totalPages])

  const openTrace = (traceId: string) => {
    setSelectedTrace(traceId)
    setDrawerOpen(true)
  }

  const rangeStart = traces.length === 0 ? 0 : (page - 1) * PAGE_SIZE + 1
  const rangeEnd = Math.min(page * PAGE_SIZE, traces.length)

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Trace 控制台</h1>
        <p className="text-muted-foreground text-xs">
          Agent 链路可观测 — 审计日志 + 执行图快照 + NDJSON 回放
        </p>
      </div>
      <ForbiddenBanner />
      {capabilityFilter ? (
        <p className="text-muted-foreground text-xs">
          按 capability 过滤：<code>{capabilityFilter}</code>
        </p>
      ) : null}
      {err ? (
        <p className="text-destructive text-sm" role="alert">
          {err}
        </p>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">筛选</CardTitle>
          <CardDescription className="text-xs">
            按 trace_id / action 过滤；点击行查看链路详情（默认按最近活动时间倒序）
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="tr-id">trace_id</Label>
              <Input
                id="tr-id"
                placeholder="tr_..."
                value={traceFilter}
                onChange={(e) => setTraceFilter(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="tr-act">action</Label>
              <Input
                id="tr-act"
                placeholder="e.g. chat / capability.governance"
                value={action}
                onChange={(e) => setAction(e.target.value)}
              />
            </div>
          </div>
          <Button type="button" disabled={busy} onClick={() => void load()}>
            查询
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 gap-2">
          <div>
            <CardTitle className="text-sm font-semibold">请求链路</CardTitle>
            <CardDescription className="text-xs">
              {traces.length > 0
                ? `共 ${traces.length} 条 · 显示 ${rangeStart}–${rangeEnd}`
                : '暂无记录'}
            </CardDescription>
          </div>
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            disabled={busy}
            aria-label="刷新链路列表"
            title="刷新"
            onClick={() => void load()}
          >
            <RefreshCw className={busy ? 'animate-spin' : undefined} />
          </Button>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>trace_id</TableHead>
                <TableHead>用户</TableHead>
                <TableHead>租户</TableHead>
                <TableHead>事件</TableHead>
                <TableHead>tokens</TableHead>
                <TableHead>耗时</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>时间</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pageTraces.map((t) => (
                <TableRow
                  key={t.trace_id}
                  className="cursor-pointer hover:bg-muted/50"
                  onClick={() => openTrace(t.trace_id)}
                >
                  <TableCell className="max-w-[140px] truncate font-mono text-xs">
                    {t.trace_id}
                  </TableCell>
                  <TableCell className="text-xs">{t.user_id}</TableCell>
                  <TableCell className="text-xs">{t.tenant_id}</TableCell>
                  <TableCell className="max-w-[160px] truncate text-xs">
                    {t.actions.join(', ')}
                  </TableCell>
                  <TableCell className="tabular-nums text-xs">{t.total_tokens}</TableCell>
                  <TableCell className="tabular-nums text-xs">{t.max_latency_ms}ms</TableCell>
                  <TableCell className="text-xs">
                    {t.error_code ? (
                      <span className="text-red-600">{t.error_code}</span>
                    ) : (
                      <span className="text-emerald-600">ok</span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs whitespace-nowrap">{t.last_activity_at}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {traces.length === 0 && !err ? (
            <p className="text-muted-foreground mt-2 text-xs">无链路记录</p>
          ) : null}
          {traces.length > 0 ? (
            <div className="mt-3 flex items-center justify-between gap-2">
              <p className="text-muted-foreground text-xs">
                第 {page} / {totalPages} 页 · 每页 {PAGE_SIZE} 条
              </p>
              <div className="flex items-center gap-1">
                <Button
                  type="button"
                  variant="outline"
                  size="icon-sm"
                  disabled={busy || page <= 1}
                  aria-label="上一页"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  <ChevronLeft />
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="icon-sm"
                  disabled={busy || page >= totalPages}
                  aria-label="下一页"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                >
                  <ChevronRight />
                </Button>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <TraceDetailDrawer
        traceId={selectedTrace}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
      />
    </div>
  )
}
