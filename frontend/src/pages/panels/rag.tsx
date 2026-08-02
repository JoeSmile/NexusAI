import { useEffect, useRef, useState } from 'react'

import { ragAsk, ragSearch, ragStatus, type RagAskData, type RagStatusData } from '@/api/rag'
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
import { StatusBadge } from '@/components/ui/StatusBadge'
import { useAuthStore } from '@/stores/authStore'

export default function RagPanel() {
  const roleEpoch = useAuthStore((s) => s.roleEpoch)
  const [q, setQ] = useState('什么是 ContextGate？')
  const [ask, setAsk] = useState<RagAskData | null>(null)
  const [search, setSearch] = useState<unknown>(null)
  const [stats, setStats] = useState<RagStatusData | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const skip = useRef(true)

  const loadStatus = async () => {
    try {
      const r = await ragStatus()
      setStats(r.data)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    }
  }

  useEffect(() => {
    void loadStatus()
  }, [])

  useEffect(() => {
    if (skip.current) {
      skip.current = false
      return
    }
    setAsk(null)
    setSearch(null)
    void loadStatus()
  }, [roleEpoch])

  const onAsk = async () => {
    setBusy(true)
    setErr('')
    try {
      const r = await ragAsk(q)
      setAsk(r.data)
      await loadStatus()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const onSearch = async () => {
    setBusy(true)
    setErr('')
    try {
      const r = await ragSearch(q)
      setSearch(r.data)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const ratio = stats?.cache?.hit_ratio
  const hitPct =
    typeof ratio === 'number' ? `${(ratio * 100).toFixed(1)}%` : '—'

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">RAG</h1>
        <p className="text-muted-foreground text-xs">
          /api/rag/ask · search · status — 同问两次看 cache_hit
        </p>
      </div>
      <ForbiddenBanner />

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle className="text-sm font-semibold">缓存状态</CardTitle>
            <CardDescription className="text-muted-foreground text-xs">
              GET /api/rag/status
            </CardDescription>
          </div>
          <StatusBadge
            status={stats?.cache?.enabled ? 'success' : 'idle'}
            label={stats?.cache?.enabled ? 'cache on' : 'cache off'}
          />
        </CardHeader>
        <CardContent className="text-xs space-y-1">
          <p>
            命中率 <strong className="tabular-nums">{hitPct}</strong>
            （hit={stats?.cache?.hit ?? 0} / miss={stats?.cache?.miss ?? 0}）
          </p>
          <p className="text-muted-foreground">
            docs={stats?.document_count ?? '—'} · {stats?.status || '—'}
          </p>
          <Button type="button" size="sm" variant="outline" onClick={() => void loadStatus()}>
            刷新 status
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">提问 / 搜索</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1">
            <Label htmlFor="rag-q">问题</Label>
            <Input id="rag-q" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <div className="flex gap-2">
            <Button type="button" disabled={busy} onClick={() => void onAsk()}>
              Ask
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => void onSearch()}
            >
              Search
            </Button>
          </div>
          {err ? (
            <p className="text-destructive text-sm" role="alert">
              {err}
            </p>
          ) : null}
          {ask ? (
            <div className="space-y-2 rounded-lg border border-border p-3">
              <div className="flex items-center gap-2">
                {ask.cache_hit ? (
                  <Badge variant="success">cache_hit · 零成本</Badge>
                ) : (
                  <Badge variant="outline">cache_miss</Badge>
                )}
                <span className="text-muted-foreground text-xs tabular-nums">
                  {ask.latency_ms != null ? `${ask.latency_ms.toFixed(0)}ms` : ''}
                </span>
              </div>
              <p className="text-sm whitespace-pre-wrap">{ask.answer || '（无回答）'}</p>
            </div>
          ) : null}
          {search ? (
            <pre className="overflow-auto rounded-lg border border-border p-2 text-xs">
              {JSON.stringify(search, null, 2)}
            </pre>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}
