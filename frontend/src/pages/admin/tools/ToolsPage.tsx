import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  getConsoleHealth,
  listConsoleTools,
  type ConsoleToolSummary,
} from '@/api/adminConsole'
import { formatApiError } from '@/api/http'
import { Badge } from '@/components/ui/badge'
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
import { ConsoleSectionPage } from '@/pages/admin/console/ConsoleSectionPage'
import { ToolDetailDrawer } from '@/pages/admin/tools/ToolDetailDrawer'

const SOURCE_VARIANT: Record<string, 'default' | 'secondary' | 'outline' | 'warning'> = {
  builtin: 'default',
  mcp: 'warning',
  skill: 'secondary',
  other: 'outline',
}

const RISK_OPTIONS = ['', 'low', 'medium', 'high', 'critical']
const SOURCE_OPTIONS = ['', 'builtin', 'mcp', 'skill', 'other']
const STATUS_OPTIONS = ['', 'enabled', 'disabled']

export default function ToolsConsolePage() {
  const [items, setItems] = useState<ConsoleToolSummary[]>([])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [superAdmin, setSuperAdmin] = useState(false)
  const [consoleTenantId, setConsoleTenantId] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  const [q, setQ] = useState('')
  const [risk, setRisk] = useState('')
  const [source, setSource] = useState('')
  const [status, setStatus] = useState('')
  const [domain, setDomain] = useState('')

  const domainOptions = useMemo(() => {
    const set = new Set(items.map((i) => i.domain).filter(Boolean))
    return ['', ...Array.from(set).sort()]
  }, [items])

  const load = useCallback(async () => {
    setBusy(true)
    setErr('')
    try {
      const [health, list] = await Promise.all([
        getConsoleHealth(),
        listConsoleTools({
          q: q.trim() || undefined,
          risk: risk || undefined,
          source: source || undefined,
          status: status || undefined,
          domain: domain || undefined,
          include_disabled: true,
        }),
      ])
      setSuperAdmin(health.super_admin)
      setConsoleTenantId(health.tenant_id || '')
      setItems(list.items || [])
    } catch (e) {
      setItems([])
      setErr(formatApiError(e, 'console_access'))
    } finally {
      setBusy(false)
    }
  }, [q, risk, source, status, domain])

  useEffect(() => {
    void load()
  }, [load])

  const openDetail = (id: string) => {
    setSelectedId(id)
    setDrawerOpen(true)
  }

  const handleUpdated = (item: ConsoleToolSummary) => {
    setItems((prev) => prev.map((row) => (row.id === item.id ? { ...row, ...item } : row)))
  }

  return (
    <ConsoleSectionPage
      title="工具管理"
      description="搜索、筛选与详情编辑 — 启停、租户 allowlist、ExecPolicy（super_admin）。"
    >
      {err ? <p className="text-sm text-red-600">{err}</p> : null}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-2">
          <div>
            <CardTitle className="text-sm font-semibold">工具列表</CardTitle>
            <CardDescription className="text-xs">
              共 {items.length} 条 · 点击行查看详情
            </CardDescription>
          </div>
          <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load()}>
            刷新
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <div className="space-y-1">
              <Label htmlFor="tool-q">搜索</Label>
              <Input
                id="tool-q"
                placeholder="名称 / ID / 描述"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="tool-risk">风险</Label>
              <select
                id="tool-risk"
                className="border-input bg-background h-9 w-full rounded-lg border px-2 text-sm"
                value={risk}
                onChange={(e) => setRisk(e.target.value)}
              >
                {RISK_OPTIONS.map((v) => (
                  <option key={v || 'all'} value={v}>
                    {v || '全部'}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="tool-source">来源</Label>
              <select
                id="tool-source"
                className="border-input bg-background h-9 w-full rounded-lg border px-2 text-sm"
                value={source}
                onChange={(e) => setSource(e.target.value)}
              >
                {SOURCE_OPTIONS.map((v) => (
                  <option key={v || 'all'} value={v}>
                    {v || '全部'}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="tool-status">状态</Label>
              <select
                id="tool-status"
                className="border-input bg-background h-9 w-full rounded-lg border px-2 text-sm"
                value={status}
                onChange={(e) => setStatus(e.target.value)}
              >
                {STATUS_OPTIONS.map((v) => (
                  <option key={v || 'all'} value={v}>
                    {v || '全部'}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="tool-domain">域</Label>
              <select
                id="tool-domain"
                className="border-input bg-background h-9 w-full rounded-lg border px-2 text-sm"
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
              >
                {domainOptions.map((v) => (
                  <option key={v || 'all'} value={v}>
                    {v || '全部'}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <Button type="button" size="sm" disabled={busy} onClick={() => void load()}>
            应用过滤
          </Button>

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>来源</TableHead>
                <TableHead>风险</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>域</TableHead>
                <TableHead>描述</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow
                  key={item.id}
                  className="cursor-pointer hover:bg-slate-50"
                  onClick={() => openDetail(item.id)}
                >
                  <TableCell className="max-w-[200px] truncate font-mono text-xs">
                    {item.id}
                  </TableCell>
                  <TableCell>
                    <Badge variant={SOURCE_VARIANT[item.supply_origin] || 'outline'}>
                      {item.supply_origin}
                    </Badge>
                  </TableCell>
                  <TableCell>{item.risk_level}</TableCell>
                  <TableCell>{item.status}</TableCell>
                  <TableCell>{item.domain}</TableCell>
                  <TableCell className="max-w-[240px] truncate text-xs">
                    {item.description}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {!err && items.length === 0 ? (
            <p className="text-muted-foreground text-sm">暂无工具条目。</p>
          ) : null}
        </CardContent>
      </Card>

      <ToolDetailDrawer
        toolId={selectedId}
        open={drawerOpen}
        superAdmin={superAdmin}
        tenantId={consoleTenantId}
        onClose={() => setDrawerOpen(false)}
        onUpdated={handleUpdated}
      />
    </ConsoleSectionPage>
  )
}
