import { useEffect, useRef, useState } from 'react'

import { formatApiError } from '@/api/http'
import {
  perfBenchmark,
  perfCacheStats,
  perfMetrics,
  perfStreamsActive,
} from '@/api/perf'
import { ForbiddenBanner } from '@/components/role/RoleSwitcher'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { useAuthStore } from '@/stores/authStore'

function JsonBlock({ data }: { data: unknown }) {
  return (
    <pre className="max-h-64 overflow-auto rounded-lg border border-border p-2 text-xs">
      {data != null ? JSON.stringify(data, null, 2) : '—'}
    </pre>
  )
}

export default function PerformancePanel() {
  const roleEpoch = useAuthStore((s) => s.roleEpoch)
  const [metrics, setMetrics] = useState<unknown>(null)
  const [cache, setCache] = useState<unknown>(null)
  const [streams, setStreams] = useState<unknown>(null)
  const [bench, setBench] = useState<unknown>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const skip = useRef(true)

  const load = async () => {
    setErr('')
    const settled = await Promise.allSettled([
      perfMetrics(),
      perfCacheStats(),
      perfStreamsActive(),
    ])
    const msgs: string[] = []
    if (settled[0].status === 'fulfilled') setMetrics(settled[0].value)
    else {
      setMetrics(null)
      msgs.push(`metrics: ${formatApiError(settled[0].reason)}`)
    }
    if (settled[1].status === 'fulfilled') setCache(settled[1].value)
    else {
      setCache(null)
      msgs.push(`cache: ${formatApiError(settled[1].reason)}`)
    }
    if (settled[2].status === 'fulfilled') setStreams(settled[2].value)
    else {
      setStreams(null)
      msgs.push(`streams: ${formatApiError(settled[2].reason)}`)
    }
    setErr(msgs.join(' · '))
  }

  useEffect(() => {
    void load()
  }, [])

  useEffect(() => {
    if (skip.current) {
      skip.current = false
      return
    }
    setBench(null)
    void load()
  }, [roleEpoch])

  const onBenchmark = async () => {
    setBusy(true)
    setErr('')
    try {
      setBench(await perfBenchmark())
    } catch (e) {
      setErr(formatApiError(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Performance</h1>
        <p className="text-muted-foreground text-xs">
          /performance/metrics · cache/stats · streams/active · benchmark
        </p>
      </div>
      <ForbiddenBanner />
      {err ? (
        <p className="text-destructive text-sm" role="alert">
          {err}
        </p>
      ) : null}

      <div className="flex gap-2">
        <Button type="button" size="sm" variant="outline" onClick={() => void load()}>
          刷新指标
        </Button>
        <Button type="button" size="sm" disabled={busy} onClick={() => void onBenchmark()}>
          Run benchmark
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">Metrics</CardTitle>
          <CardDescription className="text-xs">GET /performance/metrics</CardDescription>
        </CardHeader>
        <CardContent>
          <JsonBlock data={metrics} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">Cache stats</CardTitle>
        </CardHeader>
        <CardContent>
          <JsonBlock data={cache} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">Active streams</CardTitle>
        </CardHeader>
        <CardContent>
          <JsonBlock data={streams} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">Benchmark</CardTitle>
          <CardDescription className="text-xs">GET /performance/benchmark</CardDescription>
        </CardHeader>
        <CardContent>
          <JsonBlock data={bench} />
        </CardContent>
      </Card>
    </div>
  )
}
