import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  getConsoleTool,
  patchConsoleToolStatus,
  putConsoleToolExecPolicy,
  putConsoleToolTenantAllowlist,
  type ConsoleToolDetail,
  type ConsoleToolSummary,
  type ExecPolicy,
} from '@/api/adminConsole'
import { formatApiError } from '@/api/http'
import { RightDrawer } from '@/components/agent/RightDrawer'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'

type ToolDetailDrawerProps = {
  toolId: string | null
  open: boolean
  superAdmin: boolean
  tenantId: string
  onClose: () => void
  onUpdated: (item: ConsoleToolSummary) => void
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="bg-muted max-h-64 overflow-auto rounded-md p-3 text-xs">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

export function ToolDetailDrawer({
  toolId,
  open,
  superAdmin,
  tenantId,
  onClose,
  onUpdated,
}: ToolDetailDrawerProps) {
  const [detail, setDetail] = useState<ConsoleToolDetail | null>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [allowlistText, setAllowlistText] = useState('')
  const [execPolicy, setExecPolicy] = useState<ExecPolicy | null>(null)

  useEffect(() => {
    if (!open || !toolId) {
      setDetail(null)
      setErr('')
      return
    }
    void (async () => {
      setBusy(true)
      setErr('')
      try {
        const d = await getConsoleTool(toolId)
        setDetail(d)
        setAllowlistText((d.tenant_allowlist || []).join(', '))
        setExecPolicy(d.exec_policy)
      } catch (e) {
        setDetail(null)
        setErr(formatApiError(e, 'console_access'))
      } finally {
        setBusy(false)
      }
    })()
  }, [open, toolId])

  const handleStatusToggle = async (enabled: boolean) => {
    if (!toolId || !superAdmin) return
    setBusy(true)
    setErr('')
    try {
      const r = await patchConsoleToolStatus(toolId, enabled ? 'enabled' : 'disabled')
      setDetail((prev) => (prev ? { ...prev, ...r.item } : prev))
      onUpdated(r.item)
    } catch (e) {
      setErr(formatApiError(e, 'super_admin'))
    } finally {
      setBusy(false)
    }
  }

  const saveAllowlist = async () => {
    if (!toolId) return
    setBusy(true)
    setErr('')
    try {
      const ids = superAdmin
        ? allowlistText
            .split(/[,\s]+/)
            .map((s) => s.trim())
            .filter(Boolean)
        : allowlistText.trim()
          ? [tenantId]
          : []
      const r = await putConsoleToolTenantAllowlist(toolId, ids)
      setAllowlistText(r.tenant_allowlist.join(', '))
      setDetail((prev) => (prev ? { ...prev, ...r.item } : prev))
      onUpdated(r.item)
    } catch (e) {
      setErr(formatApiError(e, 'console_access'))
    } finally {
      setBusy(false)
    }
  }

  const saveExecPolicy = async () => {
    if (!toolId || !execPolicy || !superAdmin) return
    setBusy(true)
    setErr('')
    try {
      const r = await putConsoleToolExecPolicy(toolId, execPolicy)
      setExecPolicy(r.exec_policy)
      setDetail((prev) => (prev ? { ...prev, ...r.item, exec_policy: r.exec_policy } : prev))
      onUpdated(r.item)
    } catch (e) {
      setErr(formatApiError(e, 'super_admin'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <RightDrawer
      open={open}
      title={detail?.name || toolId || '工具详情'}
      onClose={onClose}
      className="right-drawer-panel--wide"
    >
      {busy && !detail ? <p className="text-muted-foreground text-sm">加载中…</p> : null}
      {err ? <p className="text-sm text-red-600">{err}</p> : null}
      {detail ? (
        <div className="space-y-5 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">{detail.supply_origin}</Badge>
            <Badge variant="secondary">{detail.risk_level}</Badge>
            <Badge>{detail.status}</Badge>
            {detail.requires_approval ? (
              <Badge variant="warning">需审批</Badge>
            ) : null}
          </div>

          <div className="space-y-1">
            <div className="text-muted-foreground text-xs">ID</div>
            <div className="font-mono text-xs break-all">{detail.id}</div>
          </div>

          <div className="space-y-1">
            <div className="text-muted-foreground text-xs">描述</div>
            <p>{detail.description}</p>
          </div>

          {superAdmin ? (
            <div className="flex items-center justify-between rounded-md border p-3">
              <Label htmlFor="tool-enabled">全局启停</Label>
              <Switch
                id="tool-enabled"
                checked={detail.status === 'enabled'}
                disabled={busy}
                onCheckedChange={(v) => void handleStatusToggle(v)}
              />
            </div>
          ) : null}

          <div className="space-y-2">
            <Label htmlFor="tenant-allowlist">租户 allowlist（逗号分隔，空=不限制）</Label>
            <Input
              id="tenant-allowlist"
              value={allowlistText}
              disabled={busy || (!superAdmin && false)}
              onChange={(e) => setAllowlistText(e.target.value)}
              placeholder={superAdmin ? 't1, t2' : tenantId}
            />
            {!superAdmin ? (
              <p className="text-muted-foreground text-xs">
                租户管理员仅可为本租户 `{tenantId}` 申请访问；留空则移除本租户。
              </p>
            ) : null}
            <Button type="button" size="sm" disabled={busy} onClick={() => void saveAllowlist()}>
              保存 allowlist
            </Button>
          </div>

          {superAdmin && execPolicy ? (
            <div className="space-y-3 rounded-md border p-3">
              <div className="font-medium">ExecPolicy</div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1">
                  <Label htmlFor="ep-timeout">timeout_s</Label>
                  <Input
                    id="ep-timeout"
                    type="number"
                    value={execPolicy.timeout_s}
                    onChange={(e) =>
                      setExecPolicy((p) =>
                        p ? { ...p, timeout_s: Number(e.target.value) } : p,
                      )
                    }
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="ep-retries">max_retries</Label>
                  <Input
                    id="ep-retries"
                    type="number"
                    value={execPolicy.max_retries}
                    onChange={(e) =>
                      setExecPolicy((p) =>
                        p ? { ...p, max_retries: Number(e.target.value) } : p,
                      )
                    }
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="ep-rate">rate_limit_per_min</Label>
                  <Input
                    id="ep-rate"
                    type="number"
                    value={execPolicy.rate_limit_per_min}
                    onChange={(e) =>
                      setExecPolicy((p) =>
                        p ? { ...p, rate_limit_per_min: Number(e.target.value) } : p,
                      )
                    }
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="ep-payload">max_payload_bytes</Label>
                  <Input
                    id="ep-payload"
                    type="number"
                    value={execPolicy.max_payload_bytes}
                    onChange={(e) =>
                      setExecPolicy((p) =>
                        p ? { ...p, max_payload_bytes: Number(e.target.value) } : p,
                      )
                    }
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="ep-isolation">isolation_mode</Label>
                  <Input
                    id="ep-isolation"
                    value={execPolicy.isolation_mode}
                    onChange={(e) =>
                      setExecPolicy((p) =>
                        p ? { ...p, isolation_mode: e.target.value } : p,
                      )
                    }
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="ep-mcp">max_concurrent_mcp_subprocess</Label>
                  <Input
                    id="ep-mcp"
                    type="number"
                    value={execPolicy.max_concurrent_mcp_subprocess}
                    onChange={(e) =>
                      setExecPolicy((p) =>
                        p
                          ? { ...p, max_concurrent_mcp_subprocess: Number(e.target.value) }
                          : p,
                      )
                    }
                  />
                </div>
              </div>
              <Button type="button" size="sm" disabled={busy} onClick={() => void saveExecPolicy()}>
                保存 ExecPolicy
              </Button>
            </div>
          ) : null}

          <div className="space-y-2">
            <div className="font-medium">ToolContract</div>
            <JsonBlock value={detail.tool_contract} />
          </div>

          <div className="flex gap-2">
            <Button type="button" size="sm" variant="outline" asChild>
              <Link to={`/admin/traces?capability_id=${encodeURIComponent(detail.id)}`}>
                查看调用轨迹
              </Link>
            </Button>
          </div>
        </div>
      ) : null}
    </RightDrawer>
  )
}
