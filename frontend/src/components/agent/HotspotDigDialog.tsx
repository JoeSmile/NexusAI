/**
 * 抓取相关热点 — 配置弹窗（对齐 docs/modal.html 配色；提交后再就地执行）。
 */
import { useCallback, useEffect, useState } from 'react'
import { CircleHelp, X } from 'lucide-react'

import { getOrgProfile } from '@/api/contentOps'
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

export const EDU_DIRECTIONS = [
  '专升本',
  '考研',
  '博士',
  '海外留学',
  '中外合作办学',
  '在职研究生',
  'MBA',
] as const

export type HotspotDigFormValues = {
  categories: string[]
  keywords?: string
  exclude_keywords?: string
  industry?: string
  region?: string
  use_org_profile: boolean
  user_note?: string
}

const MODAL = {
  overlay: 'bg-[rgba(15,23,42,0.65)] supports-backdrop-filter:backdrop-blur-none',
  shell:
    'overflow-hidden rounded-2xl bg-white shadow-[0_20px_60px_rgba(15,23,42,0.15)]',
  header:
    'flex flex-row items-center justify-between border-b border-[#E2E8F0] px-6 py-4 text-left',
  title: 'text-lg font-bold tracking-tight text-[#0F172A]',
  body: 'max-h-[min(85vh,720px)] space-y-4 overflow-y-auto bg-white px-6 py-5',
  footer:
    'm-0 gap-3 rounded-none border-t border-[#E2E8F0] bg-white px-6 py-4 sm:justify-end',
  label: 'text-sm font-semibold text-[#334155]',
  input:
    'h-11 rounded-xl border-[#E2E8F0] bg-[#F8FAFC] text-[#0F172A] placeholder:text-[#94A3B8] focus-visible:border-[#165DFF] focus-visible:ring-[#165DFF]/30',
  textarea:
    'min-h-24 w-full resize-y rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] px-3 py-2.5 text-sm text-[#0F172A] placeholder:text-[#94A3B8] outline-none focus:border-[#165DFF] focus:ring-2 focus:ring-[rgba(22,93,255,0.2)]',
  cancel:
    'h-11 rounded-xl border-[#E2E8F0] px-5 font-medium text-[#334155] hover:bg-[#F8FAFC]',
  primary:
    'h-11 rounded-xl bg-[#165DFF] px-6 font-semibold text-white hover:bg-[#1263D8]',
} as const

function HintIcon({
  text,
  align = 'start',
}: {
  text: string
  align?: 'start' | 'end'
}) {
  return (
    <span className="group relative inline-flex align-middle">
      <CircleHelp
        className="size-3.5 shrink-0 cursor-help text-[#64748B]"
        aria-label={text}
      />
      <span
        role="tooltip"
        className={cn(
          'pointer-events-none absolute z-50 mb-1 hidden w-max max-w-[10.5rem]',
          'rounded-lg border border-[#E2E8F0] bg-[#0F172A] px-2 py-1',
          'text-left text-[11px] leading-snug font-normal text-white shadow-lg',
          'bottom-full group-hover:block',
          align === 'end' ? 'right-0' : 'left-0',
        )}
      >
        {text}
      </span>
    </span>
  )
}

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** 确认后由父组件就地执行 dig */
  onConfirm: (values: HotspotDigFormValues) => void
  submitting?: boolean
}

export function HotspotDigDialog({
  open,
  onOpenChange,
  onConfirm,
  submitting = false,
}: Props) {
  const [digIndustry, setDigIndustry] = useState('')
  const [digRegion, setDigRegion] = useState('')
  const [directions, setDirections] = useState<string[]>([...EDU_DIRECTIONS])
  const [keywords, setKeywords] = useState('')
  const [excludeKeywords, setExcludeKeywords] = useState('')
  const [useOrgProfile, setUseOrgProfile] = useState(true)
  const [userNote, setUserNote] = useState('')
  const [orgFocus, setOrgFocus] = useState('')
  const [orgAudience, setOrgAudience] = useState('')

  const resetFromProfile = useCallback(async () => {
    setDirections([...EDU_DIRECTIONS])
    setKeywords('')
    setExcludeKeywords('')
    setUseOrgProfile(true)
    setUserNote('')
    try {
      const p = await getOrgProfile()
      const profile = p.profile || {}
      setDigIndustry(String(profile.industry || '') || '教育培训')
      setDigRegion(
        String(profile.target_region || profile.targetRegion || ''),
      )
      setOrgFocus(String(profile.product_focus || profile.productFocus || ''))
      setOrgAudience(
        String(profile.target_audience || profile.targetAudience || ''),
      )
    } catch {
      setDigIndustry((v) => v || '教育培训')
      setDigRegion('')
      setOrgFocus('')
      setOrgAudience('')
    }
  }, [])

  useEffect(() => {
    if (!open) return
    void resetFromProfile()
  }, [open, resetFromProfile])

  const toggleDirection = (d: string) => {
    setDirections((prev) =>
      prev.includes(d) ? prev.filter((x) => x !== d) : [...prev, d],
    )
  }

  const selectAllDirections = () => setDirections([...EDU_DIRECTIONS])

  const handleConfirm = () => {
    onConfirm({
      categories: directions.length ? directions : [...EDU_DIRECTIONS],
      keywords: keywords.trim() || undefined,
      exclude_keywords: excludeKeywords.trim() || undefined,
      industry: digIndustry.trim() || undefined,
      region: digRegion.trim() || undefined,
      use_org_profile: useOrgProfile,
      user_note: userNote.trim() || undefined,
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        overlayClassName={MODAL.overlay}
        className={cn(
          'gap-0 overflow-hidden border-0 bg-transparent p-0 shadow-none ring-0',
          'sm:max-w-xl',
        )}
      >
        <div className={MODAL.shell}>
          <DialogHeader className={MODAL.header}>
            <DialogTitle className={MODAL.title}>抓取相关热点</DialogTitle>
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
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="dig-industry" className={MODAL.label}>
                  行业
                </Label>
                <Input
                  id="dig-industry"
                  className={MODAL.input}
                  value={digIndustry}
                  onChange={(e) => setDigIndustry(e.target.value)}
                  placeholder="如：教育培训"
                />
              </div>
              <div className="space-y-1.5">
                <Label
                  htmlFor="dig-region"
                  className={cn(MODAL.label, 'inline-flex items-center gap-1.5')}
                >
                  地域
                  <HintIcon
                    align="end"
                    text="不填写默认抓取全国范围热点"
                  />
                </Label>
                <Input
                  id="dig-region"
                  className={MODAL.input}
                  value={digRegion}
                  onChange={(e) => setDigRegion(e.target.value)}
                  placeholder="如：杭州 / 全国"
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <Label className={MODAL.label}>方向（可多选）</Label>
                <button
                  type="button"
                  className="text-xs font-medium text-[#165DFF] hover:underline"
                  onClick={selectAllDirections}
                >
                  全选
                </button>
              </div>
              <div className="flex flex-wrap gap-2.5">
                {EDU_DIRECTIONS.map((d) => {
                  const on = directions.includes(d)
                  return (
                    <button
                      key={d}
                      type="button"
                      onClick={() => toggleDirection(d)}
                      className={cn(
                        'rounded-full border px-4 py-2 text-sm transition',
                        on
                          ? 'border-[#165DFF] bg-[rgba(22,93,255,0.1)] font-medium text-[#165DFF]'
                          : 'border-transparent bg-[#F1F5F9] text-[#334155] hover:bg-[#E2E8F0]',
                      )}
                    >
                      {d}
                    </button>
                  )
                })}
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label
                  htmlFor="kw"
                  className={cn(MODAL.label, 'inline-flex items-center gap-1.5')}
                >
                  包含关键字
                  <HintIcon text="热点标题/正文希望包含的关键词，多个用英文逗号分隔" />
                </Label>
                <Input
                  id="kw"
                  className={MODAL.input}
                  value={keywords}
                  onChange={(e) => setKeywords(e.target.value)}
                  placeholder="如：政策,习惯"
                />
              </div>
              <div className="space-y-1.5">
                <Label
                  htmlFor="xkw"
                  className={cn(MODAL.label, 'inline-flex items-center gap-1.5')}
                >
                  过滤关键字
                  <HintIcon align="end" text="命中该关键词的热点将会被过滤排除" />
                </Label>
                <Input
                  id="xkw"
                  className={MODAL.input}
                  value={excludeKeywords}
                  onChange={(e) => setExcludeKeywords(e.target.value)}
                  placeholder="如：竞品名"
                />
              </div>
            </div>

            <label className="flex cursor-pointer items-start gap-2">
              <input
                type="checkbox"
                className="mt-1 size-4 accent-[#165DFF]"
                checked={useOrgProfile}
                onChange={(e) => setUseOrgProfile(e.target.checked)}
              />
              <span>
                <span className="block text-sm font-semibold text-[#334155]">
                  结合企业画像
                </span>
                <span className="mt-0.5 block text-xs text-[#64748B]">
                  {orgFocus || orgAudience
                    ? [
                        orgFocus && `方向「${orgFocus}」`,
                        orgAudience && `受众「${orgAudience}」`,
                      ]
                        .filter(Boolean)
                        .join(' · ')
                    : '未填产品/受众时仍可用已存机构字段'}
                </span>
              </span>
            </label>

            <div className="space-y-1.5">
              <Label
                htmlFor="user-note"
                className={cn(MODAL.label, 'inline-flex items-center gap-1.5')}
              >
                补充需求
                <HintIcon text="只影响找热点；描述内容风格、受众倾向、需要规避的表达要求" />
              </Label>
              <textarea
                id="user-note"
                className={MODAL.textarea}
                placeholder="例如：偏积极正向；结合近期教育政策；避开焦虑营销…"
                value={userNote}
                maxLength={1500}
                onChange={(e) => setUserNote(e.target.value)}
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
              disabled={submitting}
              className={MODAL.primary}
              onClick={handleConfirm}
            >
              开始挖掘
            </Button>
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  )
}
