/**
 * 生成口播稿 — 配置弹窗（与抓取热点同壳；提交后再就地执行）。
 */
import { useCallback, useEffect, useState } from 'react'
import { X } from 'lucide-react'

import {
  listArtifacts,
  listStyles,
  type ContentStyle,
  type HotspotItem,
} from '@/api/contentOps'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

export type ScriptGenFormValues = {
  creator_id: string
  hotspots: HotspotItem[]
  duration_sec: number
  extra_instruction?: string
}

const MODAL = {
  overlay: 'bg-[rgba(15,23,42,0.65)] supports-backdrop-filter:backdrop-blur-none',
  shell:
    'overflow-hidden rounded-2xl bg-white shadow-[0_20px_60px_rgba(15,23,42,0.15)]',
  header:
    'flex flex-row items-center justify-between border-b border-[#E2E8F0] px-6 py-4 text-left',
  title: 'text-lg font-bold tracking-tight text-[#0F172A]',
  body: 'max-h-[min(70vh,560px)] space-y-4 overflow-y-auto bg-white px-6 py-5',
  footer:
    'm-0 gap-3 rounded-none border-t border-[#E2E8F0] bg-white px-6 py-4 sm:justify-end',
  label: 'text-sm font-semibold text-[#334155]',
  input:
    'h-11 rounded-xl border-[#E2E8F0] bg-[#F8FAFC] text-[#0F172A] placeholder:text-[#94A3B8] focus-visible:border-[#165DFF] focus-visible:ring-[#165DFF]/30',
  textarea:
    'min-h-20 w-full resize-y rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] px-3 py-2.5 text-sm text-[#0F172A] placeholder:text-[#94A3B8] outline-none focus:border-[#165DFF] focus:ring-2 focus:ring-[rgba(22,93,255,0.2)]',
  cancel:
    'h-11 rounded-xl border-[#E2E8F0] px-5 font-medium text-[#334155] hover:bg-[#F8FAFC]',
  primary:
    'h-11 rounded-xl bg-[#165DFF] px-6 font-semibold text-white hover:bg-[#1263D8]',
} as const

function asHotspots(body: unknown): HotspotItem[] {
  if (!body || typeof body !== 'object') return []
  const items = (body as { items?: unknown }).items
  if (!Array.isArray(items)) return []
  return items.filter((x) => x && typeof x === 'object') as HotspotItem[]
}

function parsePastedTopics(text: string): HotspotItem[] {
  return text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
    .map((title) => ({ title }))
}

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: (values: ScriptGenFormValues) => void
  submitting?: boolean
  /** 从热点详情「下一步」预填选题 */
  initialHotspots?: HotspotItem[]
}

export function ScriptGenDialog({
  open,
  onOpenChange,
  onConfirm,
  submitting = false,
  initialHotspots,
}: Props) {
  const [styles, setStyles] = useState<ContentStyle[]>([])
  const [creatorId, setCreatorId] = useState('default')
  const [hotspots, setHotspots] = useState<HotspotItem[]>([])
  const [selectedTopicIdx, setSelectedTopicIdx] = useState<Set<number>>(
    () => new Set(),
  )
  const [topicPaste, setTopicPaste] = useState('')
  const [duration, setDuration] = useState(60)
  const [extraInstruction, setExtraInstruction] = useState('')
  const [loadErr, setLoadErr] = useState('')

  const refreshOptions = useCallback(async () => {
    setLoadErr('')
    try {
      const [s, arts] = await Promise.all([listStyles(), listArtifacts()])
      const items = s.items || []
      setStyles(items)
      const def =
        s.default_creator_id ||
        items.find((x) => x.is_default)?.creator_id ||
        items[0]?.creator_id ||
        'default'
      setCreatorId(def)

      const day = (arts.items || []).find((x) => x.kind === 'hotspot_day')
      let hs = asHotspots(day?.body)
      if (initialHotspots?.length) {
        const titles = new Set(
          initialHotspots.map((h) => (h.title || '').trim()).filter(Boolean),
        )
        const merged = [
          ...initialHotspots,
          ...hs.filter((h) => !titles.has((h.title || '').trim())),
        ]
        hs = merged
        setSelectedTopicIdx(new Set(initialHotspots.map((_, i) => i)))
      } else {
        setSelectedTopicIdx(new Set(hs.map((_, i) => i)))
      }
      setHotspots(hs)
      setTopicPaste('')
      setDuration(60)
      setExtraInstruction('')
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e))
      setHotspots([])
      setSelectedTopicIdx(new Set())
    }
  }, [initialHotspots])

  useEffect(() => {
    if (!open) return
    void refreshOptions()
  }, [open, refreshOptions])

  const activeStyle = styles.find((s) => s.creator_id === creatorId)

  const resolveTopics = (): HotspotItem[] => {
    const fromSelect = hotspots.filter((_, i) => selectedTopicIdx.has(i))
    if (fromSelect.length > 0) return fromSelect
    return parsePastedTopics(topicPaste)
  }

  const canSubmit =
    !submitting && (selectedTopicIdx.size > 0 || !!topicPaste.trim())

  const handleConfirm = () => {
    const topics = resolveTopics()
    if (topics.length === 0) return
    const values: ScriptGenFormValues = {
      creator_id: creatorId,
      hotspots: topics,
      duration_sec: duration || 60,
      extra_instruction: extraInstruction.trim() || undefined,
    }
    // eslint-disable-next-line no-console -- QA: inspect script.gen form
    console.log('[script.gen] dialog confirm', {
      ...values,
      style: activeStyle || null,
    })
    onConfirm(values)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        overlayClassName={MODAL.overlay}
        className={cn(
          'gap-0 overflow-hidden border-0 bg-transparent p-0 shadow-none ring-0',
          'sm:max-w-lg',
        )}
      >
        <div className={MODAL.shell}>
          <DialogHeader className={MODAL.header}>
            <DialogTitle className={MODAL.title}>生成口播稿</DialogTitle>
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
            {loadErr ? (
              <p className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                {loadErr}
              </p>
            ) : null}

            <div className="space-y-1.5">
              <Label htmlFor="script-creator" className={MODAL.label}>
                主讲风格
              </Label>
              <select
                id="script-creator"
                className={cn(MODAL.input, 'w-full px-3')}
                value={creatorId}
                onChange={(e) => setCreatorId(e.target.value)}
              >
                {styles.length === 0 ? (
                  <option value="default">default（默认）</option>
                ) : (
                  styles.map((s) => (
                    <option
                      key={s.creator_id || 'default'}
                      value={s.creator_id || 'default'}
                    >
                      {s.display_name || s.creator_id || 'default'}
                      {s.is_default ? ' · 默认' : ''}
                    </option>
                  ))
                )}
              </select>
              <p className="text-xs text-[#64748B]">
                主讲{' '}
                <span className="font-semibold text-[#0F172A]">{creatorId}</span>
                {activeStyle ? ' · 专属风格' : ' · 默认风格'} · 须选题或粘贴
              </p>
            </div>

            {hotspots.length > 0 ? (
              <div className="space-y-1.5">
                <Label className={MODAL.label}>选择话题（今日合集）</Label>
                <div className="max-h-40 space-y-1 overflow-y-auto rounded-xl border border-[#E2E8F0] bg-white p-2">
                  {hotspots.map((h, i) => (
                    <label
                      key={`${h.title}-${i}`}
                      className="flex cursor-pointer items-start gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-[rgba(22,93,255,0.06)]"
                    >
                      <input
                        type="checkbox"
                        className="mt-1 size-4 accent-[#165DFF]"
                        checked={selectedTopicIdx.has(i)}
                        onChange={() => {
                          setSelectedTopicIdx((prev) => {
                            const next = new Set(prev)
                            if (next.has(i)) next.delete(i)
                            else next.add(i)
                            return next
                          })
                        }}
                      />
                      <span>
                        <span className="font-medium text-[#0F172A]">
                          {h.title}
                        </span>
                        {h.summary ? (
                          <span className="text-[#64748B]"> — {h.summary}</span>
                        ) : null}
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            ) : (
              <p className="rounded-xl border border-dashed border-[#E2E8F0] bg-[#F8FAFC] px-3 py-2 text-xs text-[#64748B]">
                尚未挖掘热点，请在下方粘贴话题，或先去「抓取相关热点」。
              </p>
            )}

            <div className="space-y-1.5">
              <Label htmlFor="topic-paste" className={MODAL.label}>
                或粘贴话题（每行一条）
              </Label>
              <textarea
                id="topic-paste"
                className={MODAL.textarea}
                placeholder="未勾选上方话题时，用这里粘贴的内容生成"
                value={topicPaste}
                onChange={(e) => setTopicPaste(e.target.value)}
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="dur" className={MODAL.label}>
                时长（秒）
              </Label>
              <Input
                id="dur"
                type="number"
                className={MODAL.input}
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value) || 60)}
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="extra-instruction" className={MODAL.label}>
                额外要求（可选）
              </Label>
              <textarea
                id="extra-instruction"
                className={MODAL.textarea}
                placeholder="例如：更口语、少堆砌政策、加一个家长共鸣开场…"
                value={extraInstruction}
                onChange={(e) => setExtraInstruction(e.target.value)}
              />
            </div>
          </div>

          <DialogFooter className={MODAL.footer}>
            <Button
              type="button"
              variant="outline"
              className={MODAL.cancel}
              onClick={() => onOpenChange(false)}
            >
              取消
            </Button>
            <Button
              type="button"
              disabled={!canSubmit}
              className={MODAL.primary}
              onClick={handleConfirm}
            >
              生成
            </Button>
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  )
}
