import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  deprecateConsoleSkill,
  getConsoleSkill,
  getSkillEvolution,
  listConsoleSkills,
  publishConsoleSkill,
  rejectConsoleSkill,
  type SkillDetail,
  type SkillEvolution,
  type SkillSummary,
} from '@/api/adminConsole'
import { formatApiError } from '@/api/http'
import { getWorkflow, type Workflow } from '@/api/workflows'
import { startRun } from '@/api/workflowRuns'
import { RightDrawer } from '@/components/agent/RightDrawer'
import { WorkflowRunDialog } from '@/components/workflow/WorkflowRunDialog'
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
  draft: 'secondary',
  published: 'default',
  deprecated: 'outline',
}

const STATUS_OPTIONS = ['', 'draft', 'published', 'deprecated']

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="bg-muted max-h-56 overflow-auto rounded-md p-3 text-xs">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

export default function SkillsConsolePage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<SkillSummary[]>([])
  const [evolution, setEvolution] = useState<SkillEvolution | null>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<SkillDetail | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [actionMsg, setActionMsg] = useState('')
  const [runTarget, setRunTarget] = useState<Workflow | null>(null)

  const load = useCallback(async () => {
    setBusy(true)
    setErr('')
    try {
      const [list, evo] = await Promise.all([
        listConsoleSkills({
          q: q.trim() || undefined,
          status: status || undefined,
        }),
        getSkillEvolution(),
      ])
      setItems(list.items || [])
      setEvolution(evo)
    } catch (e) {
      setItems([])
      setEvolution(null)
      setErr(formatApiError(e, 'console_access'))
    } finally {
      setBusy(false)
    }
  }, [q, status])

  useEffect(() => {
    void load()
  }, [load])

  const openDetail = async (id: string) => {
    setSelectedId(id)
    setDrawerOpen(true)
    setActionMsg('')
    try {
      const d = await getConsoleSkill(id)
      setDetail(d)
    } catch (e) {
      setDetail(null)
      setActionMsg(formatApiError(e, 'console_access'))
    }
  }

  const runAction = async (action: 'publish' | 'deprecate' | 'reject') => {
    if (!selectedId) return
    setBusy(true)
    setActionMsg('')
    try {
      if (action === 'publish') {
        const r = await publishConsoleSkill(selectedId)
        setDetail(r.item)
        setActionMsg('已发布（通过发布三关）')
      } else if (action === 'deprecate') {
        const r = await deprecateConsoleSkill(selectedId)
        setDetail(r.item)
        setActionMsg('已下架为 deprecated')
      } else {
        await rejectConsoleSkill(selectedId)
        setDrawerOpen(false)
        setDetail(null)
        setActionMsg('草稿已拒绝并删除')
      }
      await load()
    } catch (e) {
      setActionMsg(formatApiError(e, 'console_access'))
    } finally {
      setBusy(false)
    }
  }

  async function onRunSkill() {
    const wid = detail?.workflow_id
    if (!wid) return
    setBusy(true)
    setActionMsg('')
    try {
      const wf = await getWorkflow(wid)
      if (!wf.ir?.inputs || Object.keys(wf.ir.inputs).length === 0) {
        const run = await startRun(wf.id)
        navigate(`/runs/${run.id}`)
        return
      }
      setRunTarget(wf)
    } catch (e) {
      setActionMsg(formatApiError(e, 'run'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <ConsoleSectionPage
      title="Skill 管理"
      description="skill_assets 生命周期：draft → publish（三关闸门）→ published → deprecated"
    >
      {err ? <p className="text-sm text-red-600">{err}</p> : null}

      {evolution ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-semibold">进化器状态</CardTitle>
            <CardDescription className="text-xs">
              命中代理 = successes/uses；萃取队列 = mined draft 数
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <div>总数：{evolution.total}</div>
            <div>draft：{evolution.by_status.draft ?? 0}</div>
            <div>published：{evolution.by_status.published ?? 0}</div>
            <div>萃取队列：{evolution.mined_draft_queue}</div>
            <div>总命中：{evolution.total_uses}</div>
            <div>命中率代理：{(evolution.cache_hit_rate_proxy * 100).toFixed(1)}%</div>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle className="text-sm font-semibold">Skill 列表</CardTitle>
            <CardDescription className="text-xs">点击行查看 CoT / PlanIR</CardDescription>
          </div>
          <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load()}>
            刷新
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="skill-q">搜索</Label>
              <Input id="skill-q" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="skill-status">状态</Label>
              <select
                id="skill-status"
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
          </div>
          <Button type="button" size="sm" disabled={busy} onClick={() => void load()}>
            应用过滤
          </Button>

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>名称</TableHead>
                <TableHead>域</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>来源</TableHead>
                <TableHead>命中</TableHead>
                <TableHead>版本</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow
                  key={item.id}
                  className="cursor-pointer hover:bg-slate-50"
                  onClick={() => void openDetail(item.id)}
                >
                  <TableCell className="font-mono text-xs">{item.name}</TableCell>
                  <TableCell>{item.domain}</TableCell>
                  <TableCell>
                    <Badge variant={STATUS_VARIANT[item.status] || 'outline'}>
                      {item.status}
                    </Badge>
                  </TableCell>
                  <TableCell>{item.source}</TableCell>
                  <TableCell>{item.usage.uses}</TableCell>
                  <TableCell>v{item.version}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <RightDrawer
        open={drawerOpen}
        title={detail?.name || 'Skill 详情'}
        onClose={() => setDrawerOpen(false)}
        className="right-drawer-panel--wide"
      >
        {actionMsg ? <p className="text-muted-foreground mb-3 text-sm">{actionMsg}</p> : null}
        {detail ? (
          <div className="space-y-4 text-sm">
            <div className="flex flex-wrap gap-2">
              <Badge>{detail.status}</Badge>
              <Badge variant="outline">{detail.source}</Badge>
              <Badge variant="secondary">v{detail.version}</Badge>
            </div>
            <p className="text-muted-foreground text-xs">{detail.description}</p>
            <div>
              <div className="mb-1 font-medium">命中统计</div>
              <p className="text-xs">
                uses={detail.usage.uses} · successes={detail.usage.successes} · hit_rate=
                {(detail.usage.hit_rate * 100).toFixed(1)}% · avg_tokens=
                {detail.usage.avg_tokens.toFixed(1)}
              </p>
            </div>
            <div>
              <div className="mb-1 font-medium">CoT 模板</div>
              <pre className="bg-muted whitespace-pre-wrap rounded-md p-3 text-xs">
                {detail.cot_template}
              </pre>
            </div>
            <div>
              <div className="mb-1 font-medium">PlanIR 骨架</div>
              <JsonBlock value={detail.ir_skeleton} />
            </div>
            <div className="flex flex-wrap gap-2">
              {detail.status === 'draft' ? (
                <>
                  <Button
                    type="button"
                    size="sm"
                    disabled={busy}
                    onClick={() => void runAction('publish')}
                  >
                    发布（三关）
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => void runAction('reject')}
                  >
                    拒绝草稿
                  </Button>
                </>
              ) : null}
              {detail.status === 'published' ? (
                <>
                  {detail.workflow_id ? (
                    <Button
                      type="button"
                      size="sm"
                      disabled={busy}
                      onClick={() => void onRunSkill()}
                    >
                      运行
                    </Button>
                  ) : null}
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => void runAction('deprecate')}
                  >
                    下架
                  </Button>
                </>
              ) : null}
            </div>
          </div>
        ) : null}
      </RightDrawer>
      <WorkflowRunDialog
        workflow={runTarget}
        busy={busy}
        onClose={() => setRunTarget(null)}
        onError={setActionMsg}
        onSubmit={async (input) => {
          if (!runTarget) return
          const run = await startRun(runTarget.id, input)
          setRunTarget(null)
          navigate(`/runs/${run.id}`)
        }}
      />
    </ConsoleSectionPage>
  )
}
