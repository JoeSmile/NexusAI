import { useMemo, useState } from 'react'
import { Download } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { HotspotTableItem, RenderActionHandler } from '@/types/render'
import type { RegisteredRenderProps } from '@/components/dynamic/ComponentRegistry'

function exportHotspotsCsv(items: HotspotTableItem[]) {
  const headers = ['title', 'category', 'score', 'summary']
  const escape = (v: unknown) => {
    const s = String(v ?? '')
    if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`
    return s
  }
  const lines = [
    headers.join(','),
    ...items.map((row) => headers.map((h) => escape(row[h as keyof HotspotTableItem])).join(',')),
  ]
  const blob = new Blob([`\uFEFF${lines.join('\n')}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `hotspots-${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

export default function HotspotTable({ payload, onAction }: RegisteredRenderProps) {
  const items = useMemo(() => {
    const raw = payload.items
    if (!Array.isArray(raw)) return [] as HotspotTableItem[]
    return raw.filter((it) => it && typeof it === 'object') as HotspotTableItem[]
  }, [payload.items])

  const [selected, setSelected] = useState<Set<number>>(new Set())

  const toggle = (idx: number) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }

  const selectedItems = items.filter((_, i) => selected.has(i))

  const onGenerateScript = () => {
    if (!selectedItems.length || !onAction) return
    const handler = onAction as RenderActionHandler
    void handler({ action: 'script.gen', hotspots: selectedItems })
  }

  if (!items.length) {
    return <p className="text-sm text-muted-foreground">暂无热点数据</p>
  }

  const day = payload.day ? String(payload.day) : ''

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium text-[#0F172A]">
          热点列表{day ? ` · ${day}` : ''}（{items.length}）
        </p>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 gap-1"
            onClick={() => exportHotspotsCsv(items)}
          >
            <Download size={14} />
            导出 CSV
          </Button>
          <Button
            type="button"
            size="sm"
            className="h-8"
            disabled={!selectedItems.length}
            onClick={onGenerateScript}
          >
            生成口播（{selectedItems.length}）
          </Button>
        </div>
      </div>
      <div className="max-h-80 overflow-auto rounded-lg border border-[#E2E8F0]">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10" />
              <TableHead>标题</TableHead>
              <TableHead className="w-24">分类</TableHead>
              <TableHead className="w-16 text-right">热度</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((row, idx) => (
              <TableRow key={`${row.title || 'row'}-${idx}`}>
                <TableCell>
                  <input
                    type="checkbox"
                    checked={selected.has(idx)}
                    onChange={() => toggle(idx)}
                    aria-label={`选择 ${row.title || '热点'}`}
                  />
                </TableCell>
                <TableCell>
                  <div className="font-medium text-[#0F172A]">{row.title || '—'}</div>
                  {row.summary ? (
                    <div className="mt-0.5 text-xs text-[#64748B] line-clamp-2">{row.summary}</div>
                  ) : null}
                </TableCell>
                <TableCell className="text-sm text-[#334155]">{row.category || '—'}</TableCell>
                <TableCell className="text-right text-sm tabular-nums">
                  {row.score ?? '—'}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
