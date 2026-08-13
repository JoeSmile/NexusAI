import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { formatApiError } from '@/api/http'
import {
  createWorkflow,
  deleteWorkflow,
  forkDraft,
  listWorkflows,
  publishWorkflow,
  type Workflow,
} from '@/api/workflows'
import { startRun } from '@/api/workflowRuns'
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useAuthStore } from '@/stores/authStore'

function statusBadge(status: string) {
  const variant =
    status === 'published' ? 'default' : status === 'draft' ? 'secondary' : 'outline'
  return <Badge variant={variant}>{status}</Badge>
}

export default function WorkflowListPage() {
  const navigate = useNavigate()
  const role = useAuthStore((s) => s.activeRole)
  const roleEpoch = useAuthStore((s) => s.roleEpoch)
  const canWrite = role === 'tenant_admin' || role === 'super_admin'

  const [items, setItems] = useState<Workflow[]>([])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [newName, setNewName] = useState('')

  const load = useCallback(async () => {
    setErr('')
    setBusy(true)
    try {
      const res = await listWorkflows({ limit: 50 })
      setItems(res.items)
    } catch (e) {
      setItems([])
      setErr(formatApiError(e, 'workflow'))
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, roleEpoch])

  async function onCreate() {
    if (!newName.trim()) return
    setBusy(true)
    setErr('')
    try {
      await createWorkflow({
        name: newName.trim(),
        ir: { ir_schema: '1', nodes: [], edges: [] },
      })
      setNewName('')
      await load()
    } catch (e) {
      setErr(formatApiError(e, 'workflow'))
    } finally {
      setBusy(false)
    }
  }

  async function onPublish(w: Workflow) {
    setBusy(true)
    setErr('')
    try {
      if (!window.confirm(`发布「${w.name}」？发布后需 fork 才能再编辑。`)) return
      await publishWorkflow(w.id, w.revision)
      await load()
    } catch (e) {
      setErr(formatApiError(e, 'workflow'))
    } finally {
      setBusy(false)
    }
  }

  async function onFork(w: Workflow) {
    setBusy(true)
    setErr('')
    try {
      await forkDraft(w.id)
      await load()
    } catch (e) {
      setErr(formatApiError(e, 'workflow'))
    } finally {
      setBusy(false)
    }
  }

  async function onRun(w: Workflow) {
    setBusy(true)
    setErr('')
    try {
      const run = await startRun(w.id)
      navigate(`/runs/${run.id}`)
    } catch (e) {
      setErr(formatApiError(e, 'run'))
    } finally {
      setBusy(false)
    }
  }

  async function onDelete(w: Workflow) {
    if (!window.confirm(`删除草稿「${w.name}」？`)) return
    setBusy(true)
    setErr('')
    try {
      await deleteWorkflow(w.id)
      await load()
    } catch (e) {
      setErr(formatApiError(e, 'workflow'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4 p-4">
      <ForbiddenBanner />
      <Card>
        <CardHeader>
          <CardTitle>工作流</CardTitle>
          <CardDescription>草稿保存、发布与 fork；运行闭环见 Wave D。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {err ? <p className="text-sm text-destructive">{err}</p> : null}
          {canWrite ? (
            <div className="flex flex-wrap items-end gap-2">
              <Input
                className="max-w-xs"
                placeholder="新流程名称"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
              <Button disabled={busy || !newName.trim()} onClick={() => void onCreate()}>
                新建草稿
              </Button>
            </div>
          ) : null}

          {!busy && items.length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无工作流，创建一个草稿开始编排。</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>名称</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>revision</TableHead>
                  <TableHead>节点</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((w) => (
                  <TableRow key={w.id}>
                    <TableCell>
                      <Link className="underline" to={`/workflows/${w.id}/edit`}>
                        {w.name}
                      </Link>
                    </TableCell>
                    <TableCell>{statusBadge(w.status)}</TableCell>
                    <TableCell>{w.revision}</TableCell>
                    <TableCell>{w.ir?.nodes?.length ?? 0}</TableCell>
                    <TableCell className="space-x-2 text-right">
                      {w.status === 'draft' && canWrite ? (
                        <>
                          <Button size="sm" variant="secondary" onClick={() => void onPublish(w)}>
                            发布
                          </Button>
                          <Button size="sm" variant="destructive" onClick={() => void onDelete(w)}>
                            删除
                          </Button>
                        </>
                      ) : null}
                      {w.status === 'published' && canWrite ? (
                        <>
                          <Button size="sm" onClick={() => void onRun(w)}>
                            运行
                          </Button>
                          <Button size="sm" variant="outline" onClick={() => void onFork(w)}>
                            Fork 草稿
                          </Button>
                        </>
                      ) : null}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
