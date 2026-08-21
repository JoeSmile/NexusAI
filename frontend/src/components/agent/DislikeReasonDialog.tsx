/**
 * 差评理由弹窗 — 6 项暂定理由（可多选）+ 自由补充，提交后写入 feedback.comment。
 */
import { useEffect, useState } from 'react'

import { DISLIKE_REASONS } from '@/lib/dislikeReasons'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

type Props = {
  open: boolean
  submitting?: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (reasonIds: string[], note: string) => void
}

export function DislikeReasonDialog({
  open,
  submitting = false,
  onOpenChange,
  onSubmit,
}: Props) {
  const [selected, setSelected] = useState<string[]>([])
  const [note, setNote] = useState('')

  useEffect(() => {
    if (!open) return
    setSelected([])
    setNote('')
  }, [open])

  const canSubmit = !submitting && (selected.length > 0 || !!note.trim())

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" overlayClassName="bg-[rgba(15,23,42,0.65)]">
        <DialogHeader>
          <DialogTitle>这条回答哪里不太对？</DialogTitle>
        </DialogHeader>
        <p className="text-xs text-[#64748B]">可多选；理由为暂定，之后可改文案。</p>
        <div className="flex flex-col gap-2 py-1">
          {DISLIKE_REASONS.map((r) => {
            const on = selected.includes(r.id)
            return (
              <button
                key={r.id}
                type="button"
                className={cn(
                  'rounded-xl border px-3 py-2 text-left text-sm',
                  on
                    ? 'border-[#165DFF] bg-[#165DFF]/10 text-[#0F172A]'
                    : 'border-[#E2E8F0] bg-[#F8FAFC] text-[#334155]',
                )}
                aria-pressed={on}
                onClick={() =>
                  setSelected((cur) =>
                    cur.includes(r.id) ? cur.filter((x) => x !== r.id) : [...cur, r.id],
                  )
                }
              >
                {r.label}
              </button>
            )
          })}
        </div>
        <label className="text-sm font-semibold text-[#334155]" htmlFor="dislike-note">
          补充说明（可选）
        </label>
        <textarea
          id="dislike-note"
          className="min-h-20 w-full resize-y rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] px-3 py-2.5 text-sm outline-none focus:border-[#165DFF]"
          maxLength={500}
          placeholder="还可以写具体哪里不对…"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            disabled={submitting}
            onClick={() => onOpenChange(false)}
          >
            取消
          </Button>
          <Button
            type="button"
            disabled={!canSubmit}
            onClick={() => onSubmit(selected, note)}
          >
            {submitting ? '提交中…' : '提交差评'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
