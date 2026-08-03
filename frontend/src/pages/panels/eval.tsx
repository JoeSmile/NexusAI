import { useEffect, useRef, useState } from 'react'

import {
  evaluateBatch,
  evaluateOne,
  evalStatistics,
  listEvaluations,
  type EvalItem,
  type EvalResult,
  type EvalStatistics,
} from '@/api/eval'
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
import { useAuthStore } from '@/stores/authStore'

export default function EvalPanel() {
  const roleEpoch = useAuthStore((s) => s.roleEpoch)
  const [userMsg, setUserMsg] = useState('什么是 ContextGate？')
  const [botMsg, setBotMsg] = useState(
    'ContextGate 是企业级 LLM 前置处理网关，提供认证、护栏与路由。',
  )
  const [last, setLast] = useState<EvalResult | null>(null)
  const [rows, setRows] = useState<EvalItem[]>([])
  const [stats, setStats] = useState<EvalStatistics | null>(null)
  const [batchInfo, setBatchInfo] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const skip = useRef(true)

  const refresh = async () => {
    try {
      const [list, st] = await Promise.all([listEvaluations({ limit: 50 }), evalStatistics()])
      setRows(list.evaluations || [])
      setStats(st)
    } catch (e) {
      setErr(formatApiError(e, 'chat:write'))
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  useEffect(() => {
    if (skip.current) {
      skip.current = false
      return
    }
    setLast(null)
    setBatchInfo('')
    void refresh()
  }, [roleEpoch])

  const onEvaluate = async () => {
    setBusy(true)
    setErr('')
    try {
      const r = await evaluateOne({
        user_message: userMsg,
        bot_response: botMsg,
        session_id: 'fe-eval',
        user_id: 'fe-eval',
      })
      setLast(r)
      await refresh()
    } catch (e) {
      setErr(formatApiError(e, 'chat:write'))
    } finally {
      setBusy(false)
    }
  }

  const onBatch = async () => {
    setBusy(true)
    setErr('')
    try {
      const r = await evaluateBatch({ session_id: 'fe-eval', limit: 5 })
      setBatchInfo(JSON.stringify(r).slice(0, 400))
      await refresh()
    } catch (e) {
      setErr(formatApiError(e, 'chat:write'))
    } finally {
      setBusy(false)
    }
  }

  const avg = stats?.average_scores || {}

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Eval</h1>
        <p className="text-muted-foreground text-xs">
          /evaluation/evaluate · batch · list · statistics
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
          <CardTitle className="text-sm font-semibold">Statistics</CardTitle>
          <CardDescription className="text-xs">GET /evaluation/statistics</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2 text-xs">
          <Badge variant="outline">total={stats?.total_count ?? 0}</Badge>
          {Object.entries(avg).map(([k, v]) => (
            <Badge key={k} variant="secondary">
              {k}={typeof v === 'number' ? v.toFixed(2) : String(v)}
            </Badge>
          ))}
          <Button type="button" size="sm" variant="outline" onClick={() => void refresh()}>
            刷新
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">Evaluate</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1">
            <Label htmlFor="ev-user">user_message</Label>
            <Input id="ev-user" value={userMsg} onChange={(e) => setUserMsg(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ev-bot">bot_response</Label>
            <Input id="ev-bot" value={botMsg} onChange={(e) => setBotMsg(e.target.value)} />
          </div>
          <div className="flex gap-2">
            <Button type="button" disabled={busy} onClick={() => void onEvaluate()}>
              Evaluate
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => void onBatch()}
            >
              Batch
            </Button>
          </div>
          {last ? (
            <div className="rounded-lg border border-border p-3 text-xs space-y-1">
              <p>
                id=<span className="tabular-nums">{last.evaluation_id}</span> · avg=
                <strong className="tabular-nums">{last.average_score.toFixed(2)}</strong>
              </p>
              <p className="text-muted-foreground">{last.overall_comment || '—'}</p>
            </div>
          ) : null}
          {batchInfo ? (
            <pre className="overflow-auto rounded-lg border border-border p-2 text-xs">
              {batchInfo}
            </pre>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">List</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>id</TableHead>
                <TableHead>avg</TableHead>
                <TableHead>user_message</TableHead>
                <TableHead>created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.id}>
                  <TableCell className="tabular-nums">{r.id}</TableCell>
                  <TableCell className="tabular-nums">
                    {r.average_score != null ? Number(r.average_score).toFixed(2) : '—'}
                  </TableCell>
                  <TableCell className="max-w-[240px] truncate text-xs">
                    {r.user_message || '—'}
                  </TableCell>
                  <TableCell className="text-xs whitespace-nowrap">
                    {r.created_at || '—'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {rows.length === 0 && !err ? (
            <p className="text-muted-foreground mt-2 text-xs">暂无评估记录</p>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}
