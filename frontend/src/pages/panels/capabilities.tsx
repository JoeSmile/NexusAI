import { useEffect, useRef, useState } from 'react'

import { listCapabilities, type CapabilityItem } from '@/api/capability'
import { formatApiError } from '@/api/http'
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

const KIND_VARIANT: Record<
  string,
  'default' | 'secondary' | 'outline' | 'success' | 'warning'
> = {
  model: 'default',
  external_app: 'warning',
  agent: 'success',
  tool: 'secondary',
  datasource: 'outline',
  workflow: 'secondary',
}

export default function CapabilitiesPanel() {
  const role = useAuthStore((s) => s.activeRole)
  const roleEpoch = useAuthStore((s) => s.roleEpoch)
  const [items, setItems] = useState<CapabilityItem[]>([])
  const [kind, setKind] = useState('') // 空=全部；可选 agent 看嵌套演示
  const [includeDisabled, setIncludeDisabled] = useState(false)
  const [err, setErr] = useState('')
  const skip = useRef(true)
  const agentCount = items.filter((i) => i.kind === 'agent').length

  const load = async () => {
    setErr('')
    try {
      const r = await listCapabilities({
        kind: kind || undefined,
        include_disabled: includeDisabled,
      })
      setItems(r.items || [])
    } catch (e) {
      setItems([])
      setErr(formatApiError(e, 'chat:write'))
    }
  }

  useEffect(() => {
    void load()
  }, [])

  useEffect(() => {
    if (skip.current) {
      skip.current = false
      return
    }
    void load()
  }, [roleEpoch, role])

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Capabilities</h1>
        <p className="text-muted-foreground text-xs">
          GET /api/capabilities — 含 kind=agent（seed 后可见演示 Agent）
        </p>
      </div>
      <ForbiddenBanner />
      {err ? (
        <p className="text-destructive text-sm" role="alert">
          {err}
        </p>
      ) : null}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-2">
          <div>
            <CardTitle className="text-sm font-semibold">能力列表</CardTitle>
            <CardDescription className="text-xs">
              当前角色 <code>{role}</code> · 共 {items.length} 条
              {agentCount ? ` · agent ${agentCount}` : ''}
            </CardDescription>
          </div>
          <Button type="button" size="sm" variant="outline" onClick={() => void load()}>
            刷新
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <Label htmlFor="cap-kind">kind</Label>
              <select
                id="cap-kind"
                className="border-input bg-background h-8 rounded-lg border px-2 text-sm"
                value={kind}
                onChange={(e) => setKind(e.target.value)}
              >
                <option value="">全部</option>
                <option value="model">model</option>
                <option value="external_app">external_app</option>
                <option value="agent">agent</option>
                <option value="tool">tool</option>
                <option value="datasource">datasource</option>
                <option value="workflow">workflow</option>
              </select>
            </div>
            <label className="flex items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={includeDisabled}
                onChange={(e) => setIncludeDisabled(e.target.checked)}
              />
              include_disabled（需 admin）
            </label>
            <Button type="button" size="sm" onClick={() => void load()}>
              应用过滤
            </Button>
          </div>

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>id</TableHead>
                <TableHead>name</TableHead>
                <TableHead>kind</TableHead>
                <TableHead>provider</TableHead>
                <TableHead>status</TableHead>
                <TableHead>permission</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((c) => (
                <TableRow key={c.id}>
                  <TableCell className="font-mono text-xs">{c.id}</TableCell>
                  <TableCell className="text-xs">{c.name}</TableCell>
                  <TableCell>
                    <Badge variant={KIND_VARIANT[c.kind] || 'outline'}>{c.kind}</Badge>
                  </TableCell>
                  <TableCell className="text-xs">{c.provider}</TableCell>
                  <TableCell>
                    {c.status === 'enabled' ? (
                      <Badge variant="success">enabled</Badge>
                    ) : (
                      <Badge variant="outline">{c.status}</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-xs">{c.permission || '—'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {items.length === 0 && !err ? (
            <p className="text-muted-foreground text-xs">无可见能力</p>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}
