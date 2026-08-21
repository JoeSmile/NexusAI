/**
 * Topbar token / cost bar — today's audit_logs aggregate.
 */
import { useEffect, useState } from 'react'

import { fetchUsageSummary, type UsageSummary } from '@/api/audit'

export function TokenUsageBar() {
  const [data, setData] = useState<UsageSummary | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const s = await fetchUsageSummary()
        if (!cancelled) setData(s)
      } catch {
        if (!cancelled) setData(null)
      }
    }
    void load()
    const id = window.setInterval(() => void load(), 60_000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [])

  if (!data) return null

  const limit = Number(data.daily_limit) || 0
  const pct =
    limit > 0 ? Math.min(100, Math.round((Number(data.cost) / limit) * 100)) : 0

  return (
    <div className="token-usage" title="今日审计用量（UTC 0 点起）">
      <div className="usage-row">
        <span>今日</span>
        <span>
          {data.tokens} tok · ¥{Number(data.cost).toFixed(3)}
        </span>
      </div>
      {limit > 0 ? (
        <div className="usage-bar" aria-label={`预算已用 ${pct}%`}>
          <div className="usage-fill" style={{ width: `${pct}%` }} />
        </div>
      ) : null}
    </div>
  )
}
