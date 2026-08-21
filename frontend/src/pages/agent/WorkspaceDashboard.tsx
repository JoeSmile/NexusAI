/**
 * Workspace dashboard — coarse stats from audit + content artifacts.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { fetchUsageSummary } from '@/api/audit'
import { listArtifacts } from '@/api/contentOps'
import { formatApiError } from '@/api/http'

type Stats = {
  calls: number | null
  tokens: number | null
  cost: number | null
  hotspots: number
  scripts: number
}

export default function WorkspaceDashboard() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [hint, setHint] = useState('')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        let usageHint = ''
        const [usage, arts] = await Promise.all([
          fetchUsageSummary().catch((e) => {
            usageHint = formatApiError(e, 'audit:read')
            return null
          }),
          listArtifacts().catch(() => ({ items: [] as { kind?: string }[], count: 0 })),
        ])
        const items = arts.items || []
        if (cancelled) return
        if (usageHint) setHint(usageHint)
        setStats({
          calls: usage ? Number(usage.calls) : null,
          tokens: usage ? Number(usage.tokens) : null,
          cost: usage ? Number(usage.cost) : null,
          hotspots: items.filter((x) =>
            ['hotspot_day', 'hotspot_run', 'hotspot'].includes(String(x.kind)),
          ).length,
          scripts: items.filter((x) => x.kind === 'script').length,
        })
      } catch (e) {
        if (!cancelled) setHint(formatApiError(e))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const cards = [
    { label: '今日对话', value: stats?.calls == null ? '—' : String(stats.calls) },
    { label: '今日 tokens', value: stats?.tokens == null ? '—' : String(stats.tokens) },
    {
      label: '今日成本',
      value: stats?.cost == null ? '—' : `¥${stats.cost.toFixed(3)}`,
    },
    { label: '内容库热点/口播', value: stats ? `${stats.hotspots} / ${stats.scripts}` : '—' },
  ]

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <div>
          <h1 className="dashboard-title">工作台</h1>
          <p className="dashboard-subtitle">今日用量来自审计日志；内容条数来自内容库产物。</p>
        </div>
        <Link to="/workspace" className="btn-secondary btn-sm">
          去对话
        </Link>
      </div>
      {hint ? (
        <p className="bookmarks-hint" style={{ color: 'var(--color-danger, #dc2626)' }}>
          {hint}
        </p>
      ) : null}
      <div className="stats-grid">
        {cards.map((c) => (
          <div key={c.label} className="stat-card">
            <div className="stat-label" style={{ fontSize: 12, color: 'var(--color-gray-500)' }}>
              {c.label}
            </div>
            <div style={{ fontSize: 22, fontWeight: 700 }}>{c.value}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
