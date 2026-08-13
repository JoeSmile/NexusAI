import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { formatApiError } from '@/api/http'
import { listRuns, type WorkflowRun } from '@/api/workflowRuns'
import { ForbiddenBanner } from '@/components/role/RoleSwitcher'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useAuthStore } from '@/stores/authStore'

function formatDuration(start?: string | null, end?: string | null): string {
  if (!start || !end) return '—'
  const ms = new Date(end).getTime() - new Date(start).getTime()
  if (!Number.isFinite(ms) || ms < 0) return '—'
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60000)}m${Math.round((ms % 60000) / 1000)}s`
}

export default function RunListPage() {
  const roleEpoch = useAuthStore((s) => s.roleEpoch)
  const [items, setItems] = useState<WorkflowRun[]>([])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [offset, setOffset] = useState(0)
  const [status, setStatus] = useState('')
  const limit = 20

  const load = useCallback(async () => {
    setErr('')
    setBusy(true)
    try {
      const res = await listRuns({ limit, offset, status: status || undefined })
      setItems(res.items)
    } catch (e) {
      setItems([])
      setErr(formatApiError(e, 'run'))
    } finally {
      setBusy(false)
    }
  }, [offset, status])

  useEffect(() => {
    setOffset(0)
  }, [status])

  useEffect(() => {
    void load()
  }, [load, roleEpoch])

  return (
    <div className="space-y-4 p-4">
      <ForbiddenBanner />
      <Card>
        <CardHeader>
          <CardTitle>运行历史</CardTitle>
          <CardDescription>按组织范围列出 workflow 运行记录。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {err ? <p className="text-sm text-destructive">{err}</p> : null}
          <div className="flex items-center gap-2">
            <label className="text-sm text-muted-foreground" htmlFor="run-status-filter">
              状态
            </label>
            <select
              id="run-status-filter"
              className="h-9 rounded-md border bg-background px-3 text-sm"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="">全部</option>
              <option value="pending">pending</option>
              <option value="running">running</option>
              <option value="succeeded">succeeded</option>
              <option value="failed">failed</option>
            </select>
          </div>
          {!busy && items.length === 0 ? (
            <p className="text-sm text-muted-foreground">该流程尚未运行过（或当前范围无记录）。</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>流程</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>开始</TableHead>
                  <TableHead>结束</TableHead>
                  <TableHead>耗时</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell>
                      <Link className="underline" to={`/runs/${r.id}`}>
                        {r.workflow_name || r.workflow_id}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Badge variant={r.status === 'succeeded' ? 'default' : 'secondary'}>
                        {r.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs">{r.created_at}</TableCell>
                    <TableCell className="text-xs">{r.finished_at || '—'}</TableCell>
                    <TableCell className="text-xs">
                      {r.finished_at ? formatDuration(r.created_at, r.finished_at) : '—'}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={offset === 0 || busy}
              onClick={() => setOffset((o) => Math.max(0, o - limit))}
            >
              上一页
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={items.length < limit || busy}
              onClick={() => setOffset((o) => o + limit)}
            >
              下一页
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
