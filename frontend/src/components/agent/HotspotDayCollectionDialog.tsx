/**
 * 今日热点合集 modal — same detail UX as ContentLibrary 「今日合集」row click.
 * Loads latest hotspot_day artifact; no page navigation.
 */
import { useCallback, useEffect, useState } from 'react'
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

const MODAL = {
  overlay: 'bg-[rgba(15,23,42,0.65)] supports-backdrop-filter:backdrop-blur-none',
  shell:
    'overflow-hidden rounded-2xl bg-white shadow-[0_20px_60px_rgba(15,23,42,0.15)]',
  header:
    'flex flex-row items-center justify-between border-b border-[#E2E8F0] px-6 py-4 text-left',
  title: 'text-lg font-bold tracking-tight text-[#0F172A]',
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

type DayRow = {
  id: string
  kind: string
  title: string
  body: unknown
  created_at?: string
}

export function HotspotDayCollectionDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [busy, setBusy] = useState(false)
  const [hint, setHint] = useState('')
  const [day, setDay] = useState<DayRow | null>(null)

  const load = useCallback(async () => {
    setBusy(true)
    setHint('')
    try {
      const r = await listArtifacts()
      const days = ((r.items || []) as DayRow[]).filter((x) => x.kind === 'hotspot_day')
      // newest first if created_at present
      days.sort((a, b) =>
        String(b.created_at || '').localeCompare(String(a.created_at || '')),
      )
      setDay(days[0] ?? null)
    } catch (e) {
      setHint(formatApiError(e))
      setDay(null)
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => {
    if (!open) return
    void load()
  }, [open, load])

  const hotspots = day ? asHotspots(day.body) : []

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        overlayClassName={MODAL.overlay}
        className="gap-0 overflow-hidden border-0 bg-transparent p-0 shadow-none ring-0 sm:max-w-2xl"
      >
        <div className={MODAL.shell}>
          <DialogHeader className={MODAL.header}>
            <DialogTitle className={MODAL.title}>
              {day?.title || '今日热点合集'}
            </DialogTitle>
            <button
              type="button"
              aria-label="关闭"
              className="flex size-8 items-center justify-center rounded-lg text-[#64748B] hover:bg-[#F1F5F9] hover:text-[#0F172A]"
              onClick={() => onOpenChange(false)}
            >
              <X className="size-4" />
            </button>
          </DialogHeader>
          <div className={MODAL.body}>
            {busy ? (
              <p className="text-sm text-[#64748B]">加载中…</p>
            ) : hint ? (
              <p className="text-sm text-red-600">{hint}</p>
            ) : !day ? (
              <p className="text-sm text-[#64748B]">
                暂无今日合集 — 可先用「抓取热点」写入合集
              </p>
            ) : hotspots.length === 0 ? (
              <p className="text-sm text-[#64748B]">无热点条目</p>
            ) : (
              <ul className="space-y-2">
                {hotspots.map((h, i) => (
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
              variant="outline"
              className="h-11 rounded-xl px-4"
              disabled={busy}
              onClick={() => void load()}
            >
              刷新
            </Button>
            <Button
              type="button"
              className="h-11 rounded-xl bg-[#165DFF] px-6 font-semibold text-white hover:bg-[#1263D8]"
              onClick={() => onOpenChange(false)}
            >
              关闭
            </Button>
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  )
}
