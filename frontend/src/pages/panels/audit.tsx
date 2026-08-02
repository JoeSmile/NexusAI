import { useEffect, useState } from 'react'

import { exportAuditCsv, fetchAuditLogs, type AuditLogRow } from '@/api/audit'
import { formatApiError } from '@/api/http'
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

export default function AuditPanel() {
  const role = useAuthStore((s) => s.activeRole)
  const roleEpoch = useAuthStore((s) => s.roleEpoch)
  const [tenantId, setTenantId] = useState('')
  const [action, setAction] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [rows, setRows] = useState<AuditLogRow[]>([])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const query = {
    tenant_id: tenantId.trim() || undefined,
    action: action.trim() || undefined,
    start: start.trim() || undefined,
    end: end.trim() || undefined,
    limit: 50,
  }

  const load = async () => {
    setBusy(true)
    setErr('')
    try {
      const data = await fetchAuditLogs(query)
      setRows(data)
    } catch (e) {
      setRows([])
      setErr(formatApiError(e, 'audit:read'))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refresh on role switch only
  }, [roleEpoch, role])

  const onExport = async () => {
    setBusy(true)
    setErr('')
    try {
      await exportAuditCsv({
        tenant_id: query.tenant_id,
        start: query.start,
        end: query.end,
        action: query.action,
      })
    } catch (e) {
      setErr(formatApiError(e, 'audit:export'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Audit</h1>
        <p className="text-muted-foreground text-xs">
          当前角色 <code>{role}</code> — /api/audit/logs · export
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
          <CardTitle className="text-sm font-semibold">过滤</CardTitle>
          <CardDescription className="text-xs">
            auditor / admin 可读；user 应 403
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="space-y-1">
              <Label htmlFor="au-tid">tenant_id</Label>
              <Input
                id="au-tid"
                placeholder="跨租户角色可筛"
                value={tenantId}
                onChange={(e) => setTenantId(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="au-act">action</Label>
              <Input
                id="au-act"
                placeholder="e.g. chat"
                value={action}
                onChange={(e) => setAction(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="au-start">start (ISO)</Label>
              <Input
                id="au-start"
                value={start}
                onChange={(e) => setStart(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="au-end">end (ISO)</Label>
              <Input id="au-end" value={end} onChange={(e) => setEnd(e.target.value)} />
            </div>
          </div>
          <div className="flex gap-2">
            <Button type="button" disabled={busy} onClick={() => void load()}>
              查询
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => void onExport()}
            >
              导出 CSV
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">日志</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>id</TableHead>
                <TableHead>tenant</TableHead>
                <TableHead>action</TableHead>
                <TableHead>user</TableHead>
                <TableHead>model</TableHead>
                <TableHead>created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.id}>
                  <TableCell className="tabular-nums">{r.id}</TableCell>
                  <TableCell className="text-xs">{r.tenant_id}</TableCell>
                  <TableCell>{r.action}</TableCell>
                  <TableCell className="text-xs">{r.user_id}</TableCell>
                  <TableCell className="text-xs">{r.model || '—'}</TableCell>
                  <TableCell className="text-xs whitespace-nowrap">
                    {r.created_at || '—'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {rows.length === 0 && !err ? (
            <p className="text-muted-foreground mt-2 text-xs">无记录</p>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}
