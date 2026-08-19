/**
 * 内容库：今日合集 / 抓取记录 / 口播稿
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { X } from 'lucide-react'

import { listArtifacts, type HotspotItem } from '@/api/contentOps'
import { formatApiError } from '@/api/http'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

type TabId = 'day' | 'runs' | 'scripts'

type ArtifactRow = {
  id: string
  kind: string
  title: string
  body: unknown
  created_at?: string
}

const TABS: { id: TabId; label: string }[] = [
  { id: 'day', label: '今日合集' },
  { id: 'runs', label: '抓取记录' },
  { id: 'scripts', label: '口播稿' },
]

const MODAL = {
  overlay: 'bg-[rgba(15,23,42,0.65)] supports-backdrop-filter:backdrop-blur-none',
  shell:
    'overflow-hidden rounded-2xl bg-white shadow-[0_20px_60px_rgba(15,23,42,0.15)]',
  header:
    'flex flex-row items-center justify-between border-b border-[#E2E8F0] px-6 py-4 text-left',
  title: 'text-lg font-bold tracking-tight text-[#0F172A]',
  // 原 70vh → 约 2/3，避免瘦长；列表区内部滚动
  body: 'max-h-[min(46vh,420px)] space-y-3 overflow-y-auto bg-white px-6 py-5',
  footer:
    'm-0 gap-3 rounded-none border-t border-[#E2E8F0] bg-white px-6 py-4 sm:justify-end',
} as const

function asHotspots(body: unknown): HotspotItem[] {
  if (!body || typeof body !== 'object') return []
  const items = (body as { items?: unknown }).items
  if (!Array.isArray(items)) return []
  return items.filter((x) => x && typeof x === 'object') as HotspotItem[]
}

function asScript(body: unknown): string {
  if (!body || typeof body !== 'object') return ''
  const s = (body as { script?: unknown }).script
  return typeof s === 'string' ? s : ''
}

function kindLabel(kind: string): string {
  if (kind === 'hotspot_day') return '今日合集'
  if (kind === 'hotspot_run' || kind === 'hotspot') return '抓取'
  if (kind === 'script') return '口播'
  return kind
}

export default function ContentLibraryPage() {
  const [tab, setTab] = useState<TabId>('day')
  const [rows, setRows] = useState<ArtifactRow[]>([])
  const [hint, setHint] = useState('')
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState<ArtifactRow | null>(null)

  const refresh = useCallback(async () => {
    setBusy(true)
    setHint('')
    try {
      const r = await listArtifacts()
      setRows((r.items || []) as ArtifactRow[])
    } catch (e) {
      setHint(formatApiError(e))
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const filtered = useMemo(() => {
    if (tab === 'day') return rows.filter((r) => r.kind === 'hotspot_day')
    if (tab === 'scripts') return rows.filter((r) => r.kind === 'script')
    return rows.filter((r) => r.kind === 'hotspot_run' || r.kind === 'hotspot')
  }, [rows, tab])

  const openRow = (row: ArtifactRow) => {
    setActive(row)
    setOpen(true)
  }

  const detailHotspots = active ? asHotspots(active.body) : []
  const detailScript = active ? asScript(active.body) : ''
  const isScript = active?.kind === 'script'

  return (
    <div className="mx-auto w-full max-w-5xl flex-1 overflow-auto px-6 py-6">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A]">内容库</h1>
          <p className="mt-1 text-sm text-[#64748B]">
            今日合集为多次抓取去重后的结果；抓取记录可看每次增量；口播稿单独归档。
          </p>
        </div>
        <div className="flex gap-2">
          <Button type="button" variant="outline" disabled={busy} onClick={() => void refresh()}>
            刷新
          </Button>
          <Button type="button" variant="outline" asChild>
            <Link to="/workspace/content">内容运营</Link>
          </Button>
        </div>
      </div>

      {hint ? (
        <p className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {hint}
        </p>
      ) : null}

      <div className="mb-4 flex gap-1 border-b border-[#E2E8F0]">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={cn(
              'px-4 py-2 text-sm font-medium transition',
              tab === t.id
                ? 'border-b-2 border-[#165DFF] text-[#165DFF]'
                : 'text-[#64748B] hover:text-[#0F172A]',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="overflow-hidden rounded-2xl border border-[#E2E8F0] bg-white shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="bg-[#F8FAFC] text-xs tracking-wide text-[#64748B] uppercase">
            <tr>
              <th className="px-4 py-3 font-semibold">类型</th>
              <th className="px-4 py-3 font-semibold">标题</th>
              <th className="px-4 py-3 font-semibold">摘要</th>
              <th className="px-4 py-3 font-semibold">时间</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-10 text-center text-[#64748B]">
                  {busy
                    ? '加载中…'
                    : tab === 'day'
                      ? '暂无今日合集 — 去内容运营抓取热点'
                      : tab === 'scripts'
                        ? '暂无口播稿'
                        : '暂无抓取记录'}
                </td>
              </tr>
            ) : (
              filtered.map((row) => {
                const hs = asHotspots(row.body)
                const summary =
                  row.kind === 'script'
                    ? `${asScript(row.body).slice(0, 48)}${asScript(row.body).length > 48 ? '…' : ''}`
                    : `${hs.length} 条热点`
                return (
                  <tr
                    key={row.id}
                    className="cursor-pointer border-t border-[#E2E8F0] hover:bg-[rgba(22,93,255,0.04)]"
                    onClick={() => openRow(row)}
                  >
                    <td className="px-4 py-3">
                      <Badge variant="outline">{kindLabel(row.kind)}</Badge>
                    </td>
                    <td className="px-4 py-3 font-medium text-[#0F172A]">{row.title}</td>
                    <td className="max-w-xs truncate px-4 py-3 text-[#64748B]">{summary}</td>
                    <td className="px-4 py-3 whitespace-nowrap text-[#64748B]">
                      {row.created_at?.replace('T', ' ').slice(0, 19) || '—'}
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          showCloseButton={false}
          overlayClassName={MODAL.overlay}
          className="gap-0 overflow-hidden border-0 bg-transparent p-0 shadow-none ring-0 sm:max-w-2xl"
        >
          <div className={MODAL.shell}>
            <DialogHeader className={MODAL.header}>
              <DialogTitle className={MODAL.title}>
                {active?.title || '详情'}
              </DialogTitle>
              <button
                type="button"
                aria-label="关闭"
                className="flex size-8 items-center justify-center rounded-lg text-[#64748B] hover:bg-[#F1F5F9] hover:text-[#0F172A]"
                onClick={() => setOpen(false)}
              >
                <X className="size-4" />
              </button>
            </DialogHeader>
            <div className={MODAL.body}>
              {isScript ? (
                <pre className="whitespace-pre-wrap rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] p-3 text-sm leading-relaxed text-[#0F172A]">
                  {detailScript || '（无正文）'}
                </pre>
              ) : detailHotspots.length === 0 ? (
                <p className="text-sm text-[#64748B]">无热点条目</p>
              ) : (
                <ul className="space-y-2">
                  {detailHotspots.map((h, i) => (
                    <li
                      key={`${h.title}-${i}`}
                      className="rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] px-3 py-2"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="text-sm font-medium text-[#0F172A]">{h.title}</div>
                        {h.similar_to_previous ? (
                          <Badge variant="secondary" className="shrink-0 text-[10px]">
                            与上次近似
                          </Badge>
                        ) : null}
                      </div>
                      {h.summary ? (
                        <div className="mt-1 text-xs text-[#64748B]">{h.summary}</div>
                      ) : null}
                      {h.category ? (
                        <div className="mt-1 text-[11px] text-[#94A3B8]">{h.category}</div>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <DialogFooter className={MODAL.footer}>
              <Button
                type="button"
                className="h-11 rounded-xl bg-[#165DFF] px-6 font-semibold text-white hover:bg-[#1263D8]"
                onClick={() => setOpen(false)}
              >
                关闭
              </Button>
            </DialogFooter>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
