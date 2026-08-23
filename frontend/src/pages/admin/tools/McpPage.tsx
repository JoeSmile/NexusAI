import { useCallback, useEffect, useState } from 'react'

import {
  createMcpServer,
  deleteMcpServer,
  importMcpTools,
  listMcpServers,
  testMcpServer,
  type McpServerItem,
  type McpToolPreview,
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

const STATUS_VARIANT: Record<string, 'default' | 'secondary' | 'outline' | 'warning'> = {
  connected: 'default',
  failed: 'warning',
  circuit_open: 'warning',
  half_open: 'secondary',
  unknown: 'outline',
}

const EMPTY_FORM = {
  id: '',
  transport: 'http',
  command: '',
  args: '',
  url: 'https://example.com/mcp',
  enabled: true,
  timeout_s: 30,
}

export default function McpConsolePage() {
  const [servers, setServers] = useState<McpServerItem[]>([])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [testTools, setTestTools] = useState<McpToolPreview[]>([])
  const [selectedTools, setSelectedTools] = useState<Set<string>>(new Set())
  const [riskOverrides, setRiskOverrides] = useState<Record<string, string>>({})
  const [testMsg, setTestMsg] = useState('')

  const load = useCallback(async () => {
    setBusy(true)
    setErr('')
    try {
      const r = await listMcpServers()
      setServers(r.items || [])
    } catch (e) {
      setServers([])
      setErr(formatApiError(e, 'super_admin'))
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const createServer = async () => {
    setBusy(true)
    setErr('')
    try {
      await createMcpServer({
        id: form.id.trim(),
        transport: form.transport,
        command: form.command,
        args: form.args
          .split(/\s+/)
          .map((s) => s.trim())
          .filter(Boolean),
        url: form.url,
        enabled: form.enabled,
        timeout_s: Number(form.timeout_s),
      })
      setForm(EMPTY_FORM)
      await load()
    } catch (e) {
      setErr(formatApiError(e, 'super_admin'))
    } finally {
      setBusy(false)
    }
  }

  const runTest = async (serverId: string) => {
    setSelectedId(serverId)
    setTestMsg('')
    setTestTools([])
    setSelectedTools(new Set())
    setBusy(true)
    try {
      const r = await testMcpServer(serverId)
      if (r.ok) {
        setTestTools(r.tools || [])
        setTestMsg(`连接成功：${r.tool_count ?? 0} 个工具`)
      } else {
        setTestMsg(`连接失败：${JSON.stringify(r.error || r.status)}`)
      }
      await load()
    } catch (e) {
      setTestMsg(formatApiError(e, 'super_admin'))
    } finally {
      setBusy(false)
    }
  }

  const runImport = async () => {
    if (!selectedId || selectedTools.size === 0) return
    setBusy(true)
    setErr('')
    try {
      const r = await importMcpTools(selectedId, {
        tool_names: [...selectedTools],
        risk_overrides: riskOverrides,
      })
      setTestMsg(
        `导入完成：${r.registered.length} 成功，${r.rejected.length} 拒绝`,
      )
    } catch (e) {
      setErr(formatApiError(e, 'super_admin'))
    } finally {
      setBusy(false)
    }
  }

  const removeServer = async (serverId: string) => {
    setBusy(true)
    try {
      await deleteMcpServer(serverId)
      if (selectedId === serverId) {
        setSelectedId(null)
        setTestTools([])
      }
      await load()
    } catch (e) {
      setErr(formatApiError(e, 'super_admin'))
    } finally {
      setBusy(false)
    }
  }

  const toggleTool = (name: string) => {
    setSelectedTools((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  return (
    <ConsoleSectionPage
      title="MCP Server 管理"
      description="stdio / HTTP CRUD、连接测试、工具导入与熔断状态（super_admin）。"
    >
      {err ? <p className="text-sm text-red-600">{err}</p> : null}

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">新建 Server</CardTitle>
          <CardDescription className="text-xs">
            HTTP 示例使用 mock 模式可测；stdio 填 command/args
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <div className="space-y-1">
            <Label htmlFor="mcp-id">ID</Label>
            <Input
              id="mcp-id"
              value={form.id}
              onChange={(e) => setForm((f) => ({ ...f, id: e.target.value }))}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="mcp-transport">传输</Label>
            <select
              id="mcp-transport"
              className="border-input bg-background h-9 w-full rounded-lg border px-2 text-sm"
              value={form.transport}
              onChange={(e) => setForm((f) => ({ ...f, transport: e.target.value }))}
            >
              <option value="stdio">stdio</option>
              <option value="http">http</option>
            </select>
          </div>
          {form.transport === 'stdio' ? (
            <>
              <div className="space-y-1">
                <Label htmlFor="mcp-command">command</Label>
                <Input
                  id="mcp-command"
                  value={form.command}
                  onChange={(e) => setForm((f) => ({ ...f, command: e.target.value }))}
                />
              </div>
              <div className="space-y-1 sm:col-span-2">
                <Label htmlFor="mcp-args">args（空格分隔）</Label>
                <Input
                  id="mcp-args"
                  value={form.args}
                  onChange={(e) => setForm((f) => ({ ...f, args: e.target.value }))}
                />
              </div>
            </>
          ) : (
            <div className="space-y-1 sm:col-span-2">
              <Label htmlFor="mcp-url">URL</Label>
              <Input
                id="mcp-url"
                value={form.url}
                onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}
              />
            </div>
          )}
          <div className="flex items-end">
            <Button type="button" disabled={busy || !form.id.trim()} onClick={() => void createServer()}>
              创建
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle className="text-sm font-semibold">Server 列表</CardTitle>
            <CardDescription className="text-xs">连接测试后可勾选工具导入</CardDescription>
          </div>
          <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load()}>
            刷新
          </Button>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>传输</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>熔断</TableHead>
                <TableHead>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {servers.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="font-mono text-xs">{s.id}</TableCell>
                  <TableCell>{s.transport}</TableCell>
                  <TableCell>
                    <Badge variant={STATUS_VARIANT[s.display_status] || 'outline'}>
                      {s.display_status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs">{s.runtime?.circuit_state}</TableCell>
                  <TableCell className="space-x-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={busy}
                      onClick={() => void runTest(s.id)}
                    >
                      测试
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      disabled={busy}
                      onClick={() => void removeServer(s.id)}
                    >
                      删除
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {testMsg ? <p className="text-muted-foreground text-sm">{testMsg}</p> : null}

      {testTools.length > 0 ? (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-semibold">工具导入</CardTitle>
            <Button
              type="button"
              size="sm"
              disabled={busy || selectedTools.size === 0}
              onClick={() => void runImport()}
            >
              导入选中 ({selectedTools.size})
            </Button>
          </CardHeader>
          <CardContent className="space-y-2">
            {testTools.map((tool) => (
              <label key={tool.name} className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={selectedTools.has(tool.name)}
                  onChange={() => toggleTool(tool.name)}
                />
                <span>
                  <span className="font-mono">{tool.name}</span>
                  <span className="text-muted-foreground ml-2 text-xs">
                    {tool.property_count} props · {tool.description}
                  </span>
                </span>
                <select
                  className="border-input ml-auto rounded border px-1 text-xs"
                  value={riskOverrides[tool.name] || ''}
                  onChange={(e) =>
                    setRiskOverrides((prev) => ({
                      ...prev,
                      [tool.name]: e.target.value,
                    }))
                  }
                >
                  <option value="">自动推断</option>
                  <option value="low">low</option>
                  <option value="medium">medium</option>
                  <option value="high">high</option>
                  <option value="critical">critical</option>
                </select>
              </label>
            ))}
          </CardContent>
        </Card>
      ) : null}
    </ConsoleSectionPage>
  )
}
