import { useEffect, useState } from 'react'

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

export default function TraceConsole() {
  const role = useAuthStore((s) => s.activeRole)
  const roleEpoch = useAuthStore((s) => s.roleEpoch)
  const [traceFilter, setTraceFilter] = useState('')
  const [action, setAction] = useState('')
  const [traces, setTraces] = useState<TraceSummary[]>([])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [selectedTrace, setSelectedTrace] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  const load = async () => {
    setBusy(true)
    setErr('')
    try {
      const rows = await fetchAuditLogs({
        trace_id: traceFilter.trim() || undefined,
        action: action.trim() || undefined,
        limit: 200,
      })
      setTraces(groupAuditRowsByTrace(rows))
    } catch (e) {
      setTraces([])
      setErr(formatApiError(e, 'audit:read'))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refresh on role switch
  }, [roleEpoch, role])

  const openTrace = (traceId: string) => {
    setSelectedTrace(traceId)
    setDrawerOpen(true)
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Trace 控制台</h1>
        <p className="text-muted-foreground text-xs">
          Agent 链路可观测 — 审计日志 + 执行图快照 + NDJSON 回放
        </p>
      </div>
      <ForbiddenBanner />
      {err ? (
        <p className="text-destructive text-sm" role="alert">
          {err}
        </p>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">筛选</CardTitle>
          <CardDescription className="text-xs">
            按 trace_id / action 过滤；点击行查看链路详情
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
        <CardHeader>
          <CardTitle className="text-sm font-semibold">请求链路</CardTitle>
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
              {traces.map((t) => (
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
                  <TableCell className="text-xs whitespace-nowrap">{t.started_at}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {traces.length === 0 && !err ? (
            <p className="text-muted-foreground mt-2 text-xs">无链路记录</p>
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
