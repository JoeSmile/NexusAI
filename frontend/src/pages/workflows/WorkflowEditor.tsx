import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { listCapabilities, type CapabilityItem } from '@/api/capability'
import { formatApiError } from '@/api/http'
import {
  getWorkflow,
  patchWorkflow,
  publishWorkflow,
  type Workflow,
  type WorkflowNode,
} from '@/api/workflows'
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useAuthStore } from '@/stores/authStore'

function emptyNode(caps: CapabilityItem[]): WorkflowNode {
  const first = caps[0]
  return {
    node_id: `n_${Date.now().toString(36)}`,
    capability_id: first?.id ?? '',
    kind: 'capability',
    params: {},
    requestable: false,
  }
}

export default function WorkflowEditorPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const role = useAuthStore((s) => s.activeRole)
  const canWrite = role === 'tenant_admin' || role === 'super_admin'

  const [wf, setWf] = useState<Workflow | null>(null)
  const [caps, setCaps] = useState<CapabilityItem[]>([])
  const [name, setName] = useState('')
  const [nodes, setNodes] = useState<WorkflowNode[]>([])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const readOnly = !wf || wf.status !== 'draft' || !canWrite

  const load = useCallback(async () => {
    if (!id) return
    setErr('')
    setBusy(true)
    try {
      const [w, capRes] = await Promise.all([getWorkflow(id), listCapabilities()])
      setWf(w)
      setName(w.name)
      setNodes(w.ir?.nodes ?? [])
      setCaps(capRes.items ?? [])
    } catch (e) {
      setErr(formatApiError(e, 'workflow'))
      setWf(null)
    } finally {
      setBusy(false)
    }
  }, [id])

  useEffect(() => {
    void load()
  }, [load])

  const capById = useMemo(() => {
    const m = new Map<string, CapabilityItem>()
    for (const c of caps) m.set(c.id, c)
    return m
  }, [caps])

  function updateNode(idx: number, patch: Partial<WorkflowNode>) {
    setNodes((prev) => prev.map((n, i) => (i === idx ? { ...n, ...patch } : n)))
  }

  function setParam(idx: number, key: string, value: unknown) {
    setNodes((prev) =>
      prev.map((n, i) =>
        i === idx ? { ...n, params: { ...(n.params ?? {}), [key]: value } } : n,
      ),
    )
  }

  function moveNode(idx: number, dir: -1 | 1) {
    setNodes((prev) => {
      const j = idx + dir
      if (j < 0 || j >= prev.length) return prev
      const next = [...prev]
      ;[next[idx], next[j]] = [next[j], next[idx]]
      return next
    })
  }

  async function onSave() {
    if (!wf || readOnly) return
    setBusy(true)
    setErr('')
    try {
      const updated = await patchWorkflow(wf.id, {
        base_revision: wf.revision,
        name: name.trim() || wf.name,
        ir: { ir_schema: '1', nodes, edges: [] },
      })
      setWf(updated)
      setName(updated.name)
      setNodes(updated.ir?.nodes ?? [])
    } catch (e) {
      setErr(formatApiError(e, 'workflow'))
    } finally {
      setBusy(false)
    }
  }

  async function onPublish() {
    if (!wf || readOnly) return
    if (!window.confirm('确认发布？发布后本行不可再 PATCH。')) return
    setBusy(true)
    setErr('')
    try {
      const saved = await patchWorkflow(wf.id, {
        base_revision: wf.revision,
        name: name.trim() || wf.name,
        ir: { ir_schema: '1', nodes, edges: [] },
      })
      const published = await publishWorkflow(saved.id, saved.revision)
      setWf(published)
      navigate('/workflows')
    } catch (e) {
      setErr(formatApiError(e, 'workflow'))
    } finally {
      setBusy(false)
    }
  }

  if (!id) {
    return <p className="p-4 text-sm">缺少 workflow id</p>
  }

  return (
    <div className="space-y-4 p-4">
      <ForbiddenBanner />
      <div className="flex items-center gap-2 text-sm">
        <Link className="underline" to="/workflows">
          ← 返回列表
        </Link>
        {wf ? (
          <span className="text-muted-foreground">
            {wf.status} · rev {wf.revision}
          </span>
        ) : null}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>流程编辑器</CardTitle>
          <CardDescription>
            {readOnly
              ? '已发布流程只读；请从列表 Fork 草稿后再编辑。'
              : '选择 capability，按 param_spec 填参后保存。'}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {err ? <p className="text-sm text-destructive">{err}</p> : null}
          {busy && !wf ? <p className="text-sm text-muted-foreground">加载中…</p> : null}

          <div className="max-w-md space-y-2">
            <Label htmlFor="wf-name">名称</Label>
            <Input
              id="wf-name"
              value={name}
              disabled={readOnly || busy}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium">节点</h3>
              {!readOnly ? (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy || caps.length === 0}
                  onClick={() => setNodes((p) => [...p, emptyNode(caps)])}
                >
                  添加节点
                </Button>
              ) : null}
            </div>

            {nodes.length === 0 ? (
              <p className="text-sm text-muted-foreground">尚无节点。</p>
            ) : (
              nodes.map((node, idx) => {
                const cap = capById.get(node.capability_id)
                const ps = cap?.param_spec
                return (
                  <div key={node.node_id} className="rounded-md border p-3 space-y-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs text-muted-foreground">{node.node_id}</span>
                      {!readOnly ? (
                        <>
                          <Button size="sm" variant="ghost" onClick={() => moveNode(idx, -1)}>
                            上移
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => moveNode(idx, 1)}>
                            下移
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setNodes((p) => p.filter((_, i) => i !== idx))}
                          >
                            删除
                          </Button>
                        </>
                      ) : null}
                    </div>
                    <div className="max-w-md space-y-1">
                      <Label>Capability</Label>
                      <Select
                        disabled={readOnly}
                        value={node.capability_id}
                        onValueChange={(v) =>
                          updateNode(idx, { capability_id: v, params: {} })
                        }
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="选择能力" />
                        </SelectTrigger>
                        <SelectContent>
                          {caps.map((c) => (
                            <SelectItem key={c.id} value={c.id}>
                              {c.name} ({c.id})
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label>参数</Label>
                      {!ps || Object.keys(ps).length === 0 ? (
                        <p className="text-xs text-muted-foreground">该能力无参数</p>
                      ) : (
                        Object.entries(ps).map(([key, meta]) => {
                          const t = meta.type ?? 'string'
                          const val = node.params?.[key]
                          if (t === 'boolean') {
                            return (
                              <div key={key} className="flex items-center gap-2">
                                <input
                                  type="checkbox"
                                  disabled={readOnly}
                                  checked={Boolean(val)}
                                  onChange={(e) => setParam(idx, key, e.target.checked)}
                                />
                                <span className="text-sm">
                                  {key}
                                  {meta.required ? ' *' : ''}
                                </span>
                              </div>
                            )
                          }
                          if (t === 'enum' && meta.enum_values?.length) {
                            return (
                              <div key={key} className="max-w-md space-y-1">
                                <Label>
                                  {key}
                                  {meta.required ? ' *' : ''}
                                </Label>
                                <Select
                                  disabled={readOnly}
                                  value={String(val ?? '')}
                                  onValueChange={(v) => setParam(idx, key, v)}
                                >
                                  <SelectTrigger>
                                    <SelectValue placeholder={meta.description ?? key} />
                                  </SelectTrigger>
                                  <SelectContent>
                                    {meta.enum_values.map((ev) => (
                                      <SelectItem key={ev} value={ev}>
                                        {ev}
                                      </SelectItem>
                                    ))}
                                  </SelectContent>
                                </Select>
                              </div>
                            )
                          }
                          return (
                            <div key={key} className="max-w-md space-y-1">
                              <Label>
                                {key}
                                {meta.required ? ' *' : ''}
                              </Label>
                              <Input
                                disabled={readOnly}
                                type={t === 'number' ? 'number' : 'text'}
                                placeholder={meta.description ?? ''}
                                value={val == null ? '' : String(val)}
                                onChange={(e) => {
                                  const raw = e.target.value
                                  if (t === 'number') {
                                    setParam(idx, key, raw === '' ? undefined : Number(raw))
                                  } else {
                                    setParam(idx, key, raw)
                                  }
                                }}
                              />
                            </div>
                          )
                        })
                      )}
                    </div>
                  </div>
                )
              })
            )}
          </div>

          {!readOnly ? (
            <div className="flex gap-2">
              <Button disabled={busy} onClick={() => void onSave()}>
                保存
              </Button>
              <Button disabled={busy} variant="secondary" onClick={() => void onPublish()}>
                保存并发布
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}
