import { useCallback, useEffect, useState } from 'react'

import {
  approveRequest,
  createApiKey,
  deactivateApiKey,
  listApiKeys,
  listLlmKeys,
  listPendingRequests,
  type ApiKeyRow,
  type LlmKeyRow,
  type PendingRequest,
} from '@/api/admin'
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAuthStore } from '@/stores/authStore'

export default function AdminPanel() {
  const role = useAuthStore((s) => s.activeRole)
  const roleEpoch = useAuthStore((s) => s.roleEpoch)
  const [keys, setKeys] = useState<ApiKeyRow[]>([])
  const [llmKeys, setLlmKeys] = useState<LlmKeyRow[]>([])
  const [pending, setPending] = useState<PendingRequest[]>([])
  const [err, setErr] = useState('')
  const [userId, setUserId] = useState('qa-user')
  const [newRole, setNewRole] = useState('user')
  const [desc, setDesc] = useState('')
  const [plaintext, setPlaintext] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setErr('')
    const settled = await Promise.allSettled([
      listApiKeys(),
      listPendingRequests(),
      listLlmKeys(),
    ])
    const msgs: string[] = []

    if (settled[0].status === 'fulfilled') {
      setKeys(settled[0].value)
    } else {
      setKeys([])
      msgs.push(`api-keys: ${formatApiError(settled[0].reason, 'admin:*')}`)
    }
    if (settled[1].status === 'fulfilled') {
      setPending(settled[1].value)
    } else {
      setPending([])
      msgs.push(`pending: ${formatApiError(settled[1].reason, 'admin:approve')}`)
    }
    if (settled[2].status === 'fulfilled') {
      setLlmKeys(settled[2].value)
    } else {
      setLlmKeys([])
      msgs.push(`llm-keys: ${formatApiError(settled[2].reason, 'admin:llm_key')}`)
    }
    setErr(msgs.join(' · '))
  }, [])

  useEffect(() => {
    setPlaintext(null)
    void load()
  }, [roleEpoch, role, load])

  const onCreate = async () => {
    setBusy(true)
    setErr('')
    setCopied(false)
    try {
      const r = await createApiKey({
        user_id: userId.trim(),
        role: newRole,
        description: desc,
      })
      setPlaintext(r.api_key)
      await load()
    } catch (e) {
      setErr(formatApiError(e, 'admin:*'))
    } finally {
      setBusy(false)
    }
  }

  const onCopy = async () => {
    if (!plaintext) return
    try {
      await navigator.clipboard.writeText(plaintext)
      setCopied(true)
    } catch {
      setErr('复制失败，请手动选中复制')
    }
  }

  const onDeactivate = async (id: number) => {
    setBusy(true)
    setErr('')
    try {
      await deactivateApiKey(id)
      await load()
    } catch (e) {
      setErr(formatApiError(e, 'admin:*'))
    } finally {
      setBusy(false)
    }
  }

  const onApprove = async (request_id: number, approved: boolean) => {
    setBusy(true)
    setErr('')
    try {
      await approveRequest({ request_id, approved })
      await load()
    } catch (e) {
      setErr(formatApiError(e, 'admin:approve'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Admin</h1>
        <p className="text-muted-foreground text-xs">
          当前角色 <code>{role}</code> — api-keys / llm-keys / pending
        </p>
      </div>
      <ForbiddenBanner />
      {err ? (
        <p className="text-destructive text-sm" role="alert">
          {err}
        </p>
      ) : null}

      <Tabs defaultValue="keys">
        <TabsList>
          <TabsTrigger value="keys">API Keys</TabsTrigger>
          <TabsTrigger value="pending">Pending</TabsTrigger>
          <TabsTrigger value="llm">LLM Keys</TabsTrigger>
        </TabsList>

        <TabsContent value="keys" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-semibold">创建 API Key</CardTitle>
              <CardDescription className="text-xs">
                明文仅返回一次 — 请立即复制
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="space-y-1">
                  <Label htmlFor="ak-uid">user_id</Label>
                  <Input
                    id="ak-uid"
                    value={userId}
                    onChange={(e) => setUserId(e.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="ak-role">role</Label>
                  <select
                    id="ak-role"
                    className="border-input bg-background h-8 w-full rounded-lg border px-2 text-sm"
                    value={newRole}
                    onChange={(e) => setNewRole(e.target.value)}
                  >
                    <option value="user">user</option>
                    <option value="tenant_admin">tenant_admin</option>
                    <option value="auditor">auditor</option>
                    <option value="super_admin">super_admin</option>
                  </select>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="ak-desc">description</Label>
                  <Input
                    id="ak-desc"
                    value={desc}
                    onChange={(e) => setDesc(e.target.value)}
                  />
                </div>
              </div>
              <Button type="button" disabled={busy} onClick={() => void onCreate()}>
                创建
              </Button>
              {plaintext ? (
                <div className="space-y-2 rounded-lg border border-[var(--warning)]/40 bg-[color-mix(in_srgb,var(--warning)_8%,white)] p-3">
                  <p className="text-xs font-medium">明文 Key（关闭后不可再看）</p>
                  <code className="block break-all text-sm">{plaintext}</code>
                  <Button type="button" size="sm" variant="outline" onClick={() => void onCopy()}>
                    {copied ? '已复制' : '复制'}
                  </Button>
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-sm font-semibold">Key 列表</CardTitle>
              <Button type="button" size="sm" variant="outline" onClick={() => void load()}>
                刷新
              </Button>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>prefix</TableHead>
                    <TableHead>role</TableHead>
                    <TableHead>user</TableHead>
                    <TableHead>active</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {keys.map((k) => (
                    <TableRow key={k.id}>
                      <TableCell className="font-mono text-xs">{k.key_prefix}</TableCell>
                      <TableCell>{k.role}</TableCell>
                      <TableCell className="text-xs">{k.user_id}</TableCell>
                      <TableCell>
                        {k.is_active ? (
                          <Badge variant="success">active</Badge>
                        ) : (
                          <Badge variant="outline">off</Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        {k.is_active ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            disabled={busy}
                            onClick={() => void onDeactivate(k.id)}
                          >
                            停用
                          </Button>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {keys.length === 0 && !err ? (
                <p className="text-muted-foreground mt-2 text-xs">无数据</p>
              ) : null}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="pending">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-semibold">待审批</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {pending.length === 0 ? (
                <p className="text-muted-foreground text-xs">暂无 pending</p>
              ) : (
                pending.map((p) => (
                  <div
                    key={p.id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border p-3 text-xs"
                  >
                    <div>
                      <p className="font-medium">
                        #{p.id} {p.resource_type}/{p.resource} · {p.action}
                      </p>
                      <p className="text-muted-foreground">
                        {p.tenant_id} / {p.user_id}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        size="sm"
                        disabled={busy}
                        onClick={() => void onApprove(p.id, true)}
                      >
                        通过
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        onClick={() => void onApprove(p.id, false)}
                      >
                        拒绝
                      </Button>
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="llm">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-semibold">LLM Keys</CardTitle>
              <CardDescription className="text-xs">
                GET /api/admin/llm-keys（不返回明文）
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>alias</TableHead>
                    <TableHead>provider</TableHead>
                    <TableHead>tenant</TableHead>
                    <TableHead>active</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {llmKeys.map((k) => (
                    <TableRow key={String(k.id ?? k.key_alias)}>
                      <TableCell>{String(k.key_alias ?? '—')}</TableCell>
                      <TableCell>{String(k.provider ?? '—')}</TableCell>
                      <TableCell className="text-xs">
                        {String(k.tenant_id ?? '—')}
                      </TableCell>
                      <TableCell>
                        {k.is_active === false ? (
                          <Badge variant="outline">off</Badge>
                        ) : (
                          <Badge variant="success">active</Badge>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {llmKeys.length === 0 ? (
                <p className="text-muted-foreground mt-2 text-xs">无 LLM key</p>
              ) : null}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
