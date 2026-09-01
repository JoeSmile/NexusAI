/**
 * Task 47 — Content ops studio.
 * Company profile ≠ creator style upload (separate button, re-parse each time).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { CircleHelp } from 'lucide-react'
import { Link } from 'react-router-dom'

import {
  excludeHotspot,
  generateScript,
  getOrgProfile,
  listArtifacts,
  listStyles,
  putOrgProfile,
  uploadStyleSpeech,
  upsertStyle,
  type ContentStyle,
  type HotspotItem,
} from '@/api/contentOps'
import { formatApiError } from '@/api/http'
import {
  ScriptGenDialog,
  type ScriptGenFormValues,
} from '@/components/agent/ScriptGenDialog'
import { Badge } from '@/components/ui/badge'
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

function HintIcon({
  text,
  align = 'start',
}: {
  text: string
  /** end：贴图标右侧展开（用于右栏字段，避免撑出横向滚动条） */
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


function SectionTitle({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <h2 className="text-base font-semibold">{title}</h2>
      <HintIcon text={hint} />
    </div>
  )
}

export default function ContentStudioPage() {
  const [styles, setStyles] = useState<ContentStyle[]>([])
  const [creatorId, setCreatorId] = useState('default')
  const [newCreatorId, setNewCreatorId] = useState('')
  const [orgName, setOrgName] = useState('')
  const [orgFocus, setOrgFocus] = useState('')
  const [orgAudience, setOrgAudience] = useState('')
  const [orgIndustry, setOrgIndustry] = useState('')
  const [orgRegion, setOrgRegion] = useState('')
  const [hotspots, setHotspots] = useState<HotspotItem[]>([])
  const [scripts, setScripts] = useState<
    Array<{
      id: string
      title: string
      script: string
      creator_id?: string | null
      created_at?: string
      visibility?: 'private' | 'shared'
    }>
  >([])
  const [hint, setHint] = useState('')
  const [busy, setBusy] = useState(false)

  const [scriptOpen, setScriptOpen] = useState(false)
  const [scriptSeedHotspots, setScriptSeedHotspots] = useState<
    HotspotItem[] | undefined
  >(undefined)
  const [activeHotspot, setActiveHotspot] = useState<HotspotItem | null>(null)
  const [activeScript, setActiveScript] = useState<{
    id: string
    title: string
    script: string
    creator_id?: string | null
  } | null>(null)
  const [regenComment, setRegenComment] = useState('')

  const [styleEditOpen, setStyleEditOpen] = useState(false)
  const [styleDraft, setStyleDraft] = useState<ContentStyle>({})
  const fileRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(async () => {
    try {
      const [s, p, arts] = await Promise.all([
        listStyles(),
        getOrgProfile(),
        listArtifacts(),
      ])
      setStyles(s.items || [])
      const day = (arts.items || []).find((x) => x.kind === 'hotspot_day')
      const dayBody = day?.body as { items?: HotspotItem[] } | undefined
      if (Array.isArray(dayBody?.items)) setHotspots(dayBody.items)
      else setHotspots([])
      const scriptRows = (arts.items || [])
        .filter((x) => x.kind === 'script')
        .map((row) => {
          const body = row.body as { script?: string } | undefined
          return {
            id: row.id,
            title: row.title || '口播稿',
            script: typeof body?.script === 'string' ? body.script : '',
            creator_id: row.creator_id,
            created_at: row.created_at,
            visibility: row.visibility,
          }
        })
        .filter((r) => r.script)
      setScripts(scriptRows)
      const profile = p.profile || {}
      setOrgName(String(profile.name || ''))
      setOrgFocus(String(profile.product_focus || profile.productFocus || ''))
      setOrgAudience(String(profile.target_audience || profile.targetAudience || ''))
      setOrgIndustry(String(profile.industry || ''))
      setOrgRegion(String(profile.target_region || profile.targetRegion || ''))
    } catch (e) {
      setHint(formatApiError(e))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const activeStyle = styles.find((s) => s.creator_id === creatorId)

  const runScriptHere = async (form: ScriptGenFormValues) => {
    setBusy(true)
    setHint('正在生成口播…')
    // eslint-disable-next-line no-console -- QA context
    console.log('[script.gen] content-ops context', form)
    try {
      const r = await generateScript({
        creator_id: form.creator_id,
        hotspots: form.hotspots,
        duration_sec: form.duration_sec,
        extra_instruction: form.extra_instruction,
        save: true,
      })
      // eslint-disable-next-line no-console -- QA context
      console.log('[script.gen] content-ops response', {
        style_is_default: r.style_is_default,
        artifact_id: r.artifact_id,
        script_preview: (r.script || '').slice(0, 240),
      })
      setScriptOpen(false)
      setScriptSeedHotspots(undefined)
      setHint('口播已生成（内容运营就地，未写入对话）')
      await refresh()
    } catch (e) {
      setHint(formatApiError(e))
    } finally {
      setBusy(false)
    }
  }

  const onExcludeHotspot = async (title: string) => {
    setBusy(true)
    try {
      await excludeHotspot(title)
      setActiveHotspot(null)
      setHint(`已软删除「${title}」，下次抓取会跳过同类标题`)
      await refresh()
    } catch (e) {
      setHint(formatApiError(e))
    } finally {
      setBusy(false)
    }
  }

  const onRegenScript = async () => {
    if (!activeScript) return
    setBusy(true)
    const form = {
      creator_id: activeScript.creator_id || creatorId || 'default',
      hotspots: [{ title: activeScript.title }],
      duration_sec: 60,
      extra_instruction: regenComment.trim() || undefined,
    }
    // eslint-disable-next-line no-console -- QA context
    console.log('[script.gen] regenerate context', form)
    try {
      await generateScript({ ...form, save: true })
      setActiveScript(null)
      setRegenComment('')
      setHint('已按意见重新生成口播')
      await refresh()
    } catch (e) {
      setHint(formatApiError(e))
    } finally {
      setBusy(false)
    }
  }

  const saveOrg = async () => {
    setBusy(true)
    try {
      await putOrgProfile({
        name: orgName,
        industry: orgIndustry || undefined,
        product_focus: orgFocus,
        target_audience: orgAudience,
        target_region: orgRegion || undefined,
      })
      setHint('机构画像已保存（公司资料请走知识库 RAG，勿与风格上传混淆）')
    } catch (e) {
      setHint(formatApiError(e))
    } finally {
      setBusy(false)
    }
  }

  const onStyleFile = async (file: File | null) => {
    if (!file) return
    setBusy(true)
    setHint('')
    try {
      const r = await uploadStyleSpeech(creatorId, file)
      setStyleDraft(r.style || {})
      setHint(
        `已为「${creatorId}」重新解析风格（${r.filename}，${r.chars} 字）。换主讲请改 creator 再上传。`,
      )
      await refresh()
    } catch (e) {
      setHint(formatApiError(e))
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const saveStyleDraft = async () => {
    setBusy(true)
    try {
      await upsertStyle(creatorId, styleDraft)
      setHint(`「${creatorId}」风格摘要已手改保存`)
      setStyleEditOpen(false)
      await refresh()
    } catch (e) {
      setHint(formatApiError(e))
    } finally {
      setBusy(false)
    }
  }

  const addCreator = () => {
    const id = newCreatorId.trim().toLowerCase().replace(/\s+/g, '_')
    if (!id) return
    setCreatorId(id)
    setNewCreatorId('')
    setHint(`当前主讲切换为「${id}」— 请用下方按钮上传其演讲稿并提取风格`)
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 overflow-auto pb-10" style={{ flex: 1, width: '100%', padding: 24 }}>
      {/* Hero */}
      <section className="relative overflow-hidden rounded-2xl border border-border bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 px-6 py-7 text-white shadow-lg">
        <div
          className="pointer-events-none absolute inset-0 opacity-30"
          style={{
            backgroundImage:
              'radial-gradient(circle at 20% 20%, #38bdf8 0%, transparent 45%), radial-gradient(circle at 80% 0%, #34d399 0%, transparent 40%)',
          }}
        />
        <div className="relative flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-medium tracking-widest text-sky-200/80 uppercase">
              Content Ops
            </p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">
              内容运营工作台
            </h1>
            <p className="mt-2 max-w-xl text-sm text-slate-300">
              本页管理画像、主讲风格与工作流产物（热点/口播）。执行工作流请到「对话」页输入框上方快捷入口。
            </p>
          </div>
          <div className="relative flex flex-col items-start gap-1 text-sm">
            <Link to="/workspace" className="text-sky-200 hover:text-white underline-offset-4 hover:underline">
              去对话执行工作流
            </Link>
            <Link to="/workspace/library" className="text-sky-200 hover:text-white underline-offset-4 hover:underline">
              产物归档 → 内容库
            </Link>
            <Link to="/workspace/knowledge" className="text-sky-200 hover:text-white underline-offset-4 hover:underline">
              公司资料 → 知识库
            </Link>
          </div>
        </div>
        {hint ? (
          <p className="relative mt-4 rounded-lg bg-white/10 px-3 py-2 text-xs text-sky-50">
            {hint}
          </p>
        ) : null}
      </section>

      <div className="space-y-6">
          {/* Org */}
          <section className="rounded-xl border border-border bg-card p-5 shadow-sm">
            <div className="mb-4">
              <SectionTitle
                title="机构画像"
                hint="内容域边界（说哪家的事）。产品册/课件等公司资料请去知识库上传。"
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <div>
                <Label htmlFor="org-name">机构名</Label>
                <Input
                  id="org-name"
                  className="mt-1"
                  value={orgName}
                  onChange={(e) => setOrgName(e.target.value)}
                />
              </div>
              <div>
                <Label htmlFor="org-focus">产品/课程</Label>
                <Input
                  id="org-focus"
                  className="mt-1"
                  value={orgFocus}
                  onChange={(e) => setOrgFocus(e.target.value)}
                />
              </div>
              <div>
                <Label htmlFor="org-aud">受众</Label>
                <Input
                  id="org-aud"
                  className="mt-1"
                  value={orgAudience}
                  onChange={(e) => setOrgAudience(e.target.value)}
                />
              </div>
            </div>
            <Button
              type="button"
              size="sm"
              className="mt-4"
              disabled={busy}
              onClick={() => void saveOrg()}
            >
              保存画像
            </Button>
          </section>

          {/* Creators / style — separate from company docs */}
          <section className="rounded-xl border border-border bg-card p-5 shadow-sm">
            <div className="mb-4">
              <SectionTitle
                title="主讲风格（按人）"
                hint="小A / 小B 各有一条风格。上传演讲稿只更新当前主讲，并每次重新解析。与知识库公司资料无关。"
              />
            </div>

            <div className="mb-4 flex flex-wrap items-center gap-2">
              {(styles.length
                ? styles.map((s) => s.creator_id || 'default')
                : ['default']
              )
                .filter((v, i, a) => a.indexOf(v) === i)
                .map((id) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => setCreatorId(id || 'default')}
                    className={cn(
                      'rounded-full border px-3 py-1 text-xs transition',
                      creatorId === id
                        ? 'border-primary bg-primary text-primary-foreground'
                        : 'border-border hover:bg-muted',
                    )}
                  >
                    {id}
                  </button>
                ))}
              <div className="ml-auto flex items-center gap-2">
                <Input
                  placeholder="新主讲 id，如 xiaob"
                  className="h-8 w-36 text-xs"
                  value={newCreatorId}
                  onChange={(e) => setNewCreatorId(e.target.value)}
                />
                <Button type="button" size="sm" variant="outline" onClick={addCreator}>
                  添加主讲
                </Button>
              </div>
            </div>

            <div className="bg-muted/40 rounded-lg border border-dashed border-border p-4">
              <p className="mb-2 text-sm font-medium">
                当前：<span className="text-primary">{creatorId}</span>
                {activeStyle?.persona ? (
                  <span className="text-muted-foreground font-normal">
                    {' '}
                    · {activeStyle.persona}
                  </span>
                ) : (
                  <span className="text-muted-foreground font-normal"> · 尚未上传风格</span>
                )}
              </p>
              <div className="flex flex-wrap gap-2">
                <input
                  ref={fileRef}
                  type="file"
                  accept=".txt,.md,.pdf,.docx"
                  className="hidden"
                  onChange={(e) => void onStyleFile(e.target.files?.[0] ?? null)}
                />
                <Button
                  type="button"
                  disabled={busy}
                  onClick={() => fileRef.current?.click()}
                >
                  上传演讲稿并提取风格
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => {
                    setStyleDraft(activeStyle || { creator_id: creatorId })
                    setStyleEditOpen(true)
                  }}
                >
                  手改摘要
                </Button>
              </div>
              <p className="text-muted-foreground mt-2 text-[11px]">
                支持 txt / pdf / docx（旧 .doc 请另存 docx）。音频请先转写。每次上传都会覆盖该主讲旧摘要。
              </p>
              {activeStyle?.catchphrases?.length ? (
                <div className="mt-3 flex flex-wrap gap-1">
                  {activeStyle.catchphrases.map((c) => (
                    <Badge key={c} variant="secondary">
                      {c}
                    </Badge>
                  ))}
                </div>
              ) : null}
            </div>
          </section>

          {/* Results */}
          <div className="grid gap-4 md:grid-cols-2">
            <section className="rounded-xl border border-border bg-card p-5 shadow-sm">
              <h2 className="mb-3 text-base font-semibold">热点结果</h2>
              {hotspots.length === 0 ? (
                <p className="text-muted-foreground text-sm">
                  在「对话」页输入框上方点「抓取热点」
                </p>
              ) : (
                <ul className="max-h-72 space-y-2 overflow-auto">
                  {hotspots.map((h, i) => (
                    <li key={`${h.title}-${i}`}>
                      <button
                        type="button"
                        className="w-full rounded-lg border border-border/80 bg-background px-3 py-2 text-left transition hover:border-[#165DFF]/40 hover:bg-[rgba(22,93,255,0.04)]"
                        onClick={() => setActiveHotspot(h)}
                      >
                        <div className="text-sm font-medium text-[#0F172A]">
                          {h.core_topic || h.title}
                        </div>
                        <div className="text-muted-foreground text-xs">
                          {h.short_desc || h.summary}
                        </div>
                        <div className="text-muted-foreground mt-1 flex flex-wrap gap-2 text-[11px]">
                          {h.source ? <span>{h.source}</span> : null}
                          {h.hot_score != null || h.score != null ? (
                            <span>热度 {h.hot_score ?? h.score}</span>
                          ) : null}
                          {h.competition_level ? (
                            <span>竞争 {h.competition_level}</span>
                          ) : null}
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="rounded-xl border border-border bg-card p-5 shadow-sm">
              <h2 className="mb-3 text-base font-semibold">口播稿列表</h2>
              {scripts.length === 0 ? (
                <p className="text-muted-foreground text-sm">
                  在「对话」页生成，或从热点详情进入
                </p>
              ) : (
                <ul className="max-h-72 space-y-2 overflow-auto">
                  {scripts.map((s) => (
                    <li key={s.id}>
                      <button
                        type="button"
                        className="w-full rounded-lg border border-border/80 bg-background px-3 py-2 text-left transition hover:border-[#165DFF]/40 hover:bg-[rgba(22,93,255,0.04)]"
                        onClick={() => {
                          setActiveScript(s)
                          setRegenComment('')
                        }}
                      >
                        <div className="text-sm font-medium text-[#0F172A]">{s.title}</div>
                        <div className="mt-0.5 text-[11px] text-[#94A3B8]">
                          {s.visibility === 'shared' ? '已共享' : '私有'}
                        </div>
                        <div className="text-muted-foreground mt-0.5 line-clamp-2 text-xs">
                          {s.script.slice(0, 120)}
                          {s.script.length > 120 ? '…' : ''}
                        </div>
                        <div className="text-muted-foreground mt-1 text-[11px]">
                          {s.created_at?.replace('T', ' ').slice(0, 19) || ''}
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
      </div>

      <ScriptGenDialog
        open={scriptOpen}
        onOpenChange={(o) => {
          setScriptOpen(o)
          if (!o) setScriptSeedHotspots(undefined)
        }}
        submitting={busy}
        initialHotspots={scriptSeedHotspots}
        onConfirm={(v) => void runScriptHere(v)}
      />

      <Dialog
        open={!!activeHotspot}
        onOpenChange={(o) => {
          if (!o) setActiveHotspot(null)
        }}
      >
        <DialogContent className="flex max-h-[min(90vh,820px)] flex-col gap-0 overflow-hidden p-0 sm:max-w-2xl">
          <DialogHeader className="shrink-0 border-b border-border px-6 py-4">
            <DialogTitle className="pr-8 text-left leading-snug">
              {activeHotspot?.core_topic || activeHotspot?.title || '热点'}
            </DialogTitle>
            <p className="text-muted-foreground text-left text-xs">
              {[
                activeHotspot?.source,
                activeHotspot?.category,
                activeHotspot?.crawl_time
                  ? `抓取 ${activeHotspot.crawl_time}`
                  : null,
              ]
                .filter(Boolean)
                .join(' · ')}
            </p>
          </DialogHeader>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 py-4 text-sm">
            {activeHotspot ? (
              <>
                <p className="text-[#334155] leading-relaxed">
                  {activeHotspot.short_desc ||
                    activeHotspot.summary ||
                    '（无摘要）'}
                </p>
                <div className="flex flex-wrap gap-2 text-xs">
                  <Badge variant="secondary">
                    热度 {activeHotspot.hot_score ?? activeHotspot.score ?? '-'}
                  </Badge>
                  <Badge variant="secondary">
                    趋势 {activeHotspot.hot_trend || '-'}
                  </Badge>
                  <Badge variant="secondary">
                    竞争 {activeHotspot.competition_level || '-'}
                  </Badge>
                  <Badge variant="secondary">
                    排名 #{activeHotspot.rank ?? '-'}
                  </Badge>
                </div>
                {activeHotspot.full_summary ? (
                  <section>
                    <h3 className="mb-1 text-xs font-semibold text-[#64748B]">
                      完整摘要
                    </h3>
                    <p className="whitespace-pre-wrap leading-relaxed text-[#0F172A]">
                      {activeHotspot.full_summary}
                    </p>
                  </section>
                ) : null}
                {activeHotspot.emotion_tag?.length ? (
                  <section>
                    <h3 className="mb-1 text-xs font-semibold text-[#64748B]">
                      情绪倾向
                    </h3>
                    <p>{activeHotspot.emotion_tag.join('、')}</p>
                  </section>
                ) : null}
                {activeHotspot.content_position ? (
                  <section>
                    <h3 className="mb-1 text-xs font-semibold text-[#64748B]">
                      内容定位
                    </h3>
                    <p>{activeHotspot.content_position}</p>
                  </section>
                ) : null}
                {activeHotspot.suitable_content_type?.length ? (
                  <section>
                    <h3 className="mb-1 text-xs font-semibold text-[#64748B]">
                      内容形式
                    </h3>
                    <p>{activeHotspot.suitable_content_type.join('、')}</p>
                  </section>
                ) : null}
                {activeHotspot.target_audience ? (
                  <section>
                    <h3 className="mb-1 text-xs font-semibold text-[#64748B]">
                      人群标签
                    </h3>
                    <p>
                      主：{activeHotspot.target_audience.primary || '-'}
                      {activeHotspot.target_audience.secondary
                        ? ` · 次：${activeHotspot.target_audience.secondary}`
                        : ''}
                      {activeHotspot.target_audience.age_range
                        ? ` · ${activeHotspot.target_audience.age_range}`
                        : ''}
                    </p>
                    {activeHotspot.target_audience.pain_points?.length ? (
                      <p className="text-muted-foreground mt-1 text-xs">
                        痛点：
                        {activeHotspot.target_audience.pain_points.join('；')}
                      </p>
                    ) : null}
                  </section>
                ) : null}
                {(activeHotspot.main_keywords?.length ||
                  activeHotspot.extend_keywords?.length) && (
                  <section>
                    <h3 className="mb-1 text-xs font-semibold text-[#64748B]">
                      关键词
                    </h3>
                    <p>
                      主词：{(activeHotspot.main_keywords || []).join('、') || '-'}
                    </p>
                    {activeHotspot.extend_keywords?.length ? (
                      <p className="mt-1">
                        延伸：{activeHotspot.extend_keywords.join('、')}
                      </p>
                    ) : null}
                  </section>
                )}
                {activeHotspot.competitor_angle?.length ||
                activeHotspot.differentiate_angle ? (
                  <section>
                    <h3 className="mb-1 text-xs font-semibold text-[#64748B]">
                      竞争程度
                    </h3>
                    {activeHotspot.competitor_angle?.map((a) => (
                      <p key={a} className="text-muted-foreground">
                        · {a}
                      </p>
                    ))}
                    {activeHotspot.differentiate_angle ? (
                      <p className="mt-1">
                        差异化：{activeHotspot.differentiate_angle}
                      </p>
                    ) : null}
                  </section>
                ) : null}
                {activeHotspot.risk_tag?.length || activeHotspot.suggest_limit ? (
                  <section>
                    <h3 className="mb-1 text-xs font-semibold text-[#64748B]">
                      风险标签
                    </h3>
                    {activeHotspot.risk_tag?.length ? (
                      <p>{activeHotspot.risk_tag.join('、')}</p>
                    ) : null}
                    {activeHotspot.suggest_limit ? (
                      <p className="text-muted-foreground mt-1 text-xs">
                        建议限制：{activeHotspot.suggest_limit}
                      </p>
                    ) : null}
                  </section>
                ) : null}
                {activeHotspot.suggested_opening_hook ? (
                  <section>
                    <h3 className="mb-1 text-xs font-semibold text-[#64748B]">
                      建议开场
                    </h3>
                    <p>{activeHotspot.suggested_opening_hook}</p>
                  </section>
                ) : null}
                {activeHotspot.evidence || activeHotspot.原文摘录 ? (
                  <section className="rounded-lg border border-dashed border-[#E2E8F0] bg-[#F8FAFC] p-3">
                    <h3 className="mb-1 text-xs font-semibold text-[#64748B]">
                      素材来源 / 证据
                    </h3>
                    {(activeHotspot.原文摘录 ||
                      activeHotspot.evidence?.raw_excerpt) && (
                      <p className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-[#0F172A]">
                        <span className="font-semibold">原文摘录：</span>
                        {activeHotspot.原文摘录 ||
                          activeHotspot.evidence?.raw_excerpt}
                      </p>
                    )}
                    {activeHotspot.evidence?.crawl_note &&
                    !(
                      activeHotspot.reference_material_links?.length ||
                      activeHotspot.evidence?.source_url
                    ) ? (
                      <p className="text-muted-foreground mt-1 text-[11px]">
                        {activeHotspot.evidence.crawl_note}
                      </p>
                    ) : null}
                    {activeHotspot.reference_material_links?.length ? (
                      <p className="mt-2 text-xs">
                        参考链接：
                        {activeHotspot.reference_material_links.join('；')}
                      </p>
                    ) : activeHotspot.evidence?.source_url ? (
                      <p className="mt-2 text-xs">
                        参考链接：{activeHotspot.evidence.source_url}
                      </p>
                    ) : null}
                    {activeHotspot.data_support?.length ? (
                      <p className="mt-1 text-xs">
                        数据支撑：{activeHotspot.data_support.join('；')}
                      </p>
                    ) : null}
                  </section>
                ) : null}
              </>
            ) : null}
          </div>
          <DialogFooter className="m-0 flex !flex-row flex-wrap items-center justify-end gap-2 rounded-none border-t border-border bg-white px-6 py-4">
            <Button
              type="button"
              variant="outline"
              className="h-10 min-w-[5.5rem]"
              onClick={() => {
                if (!activeHotspot) return
                const t = JSON.stringify(activeHotspot, null, 2)
                void navigator.clipboard.writeText(t)
                setHint('已复制完整热点 JSON')
              }}
            >
              复制
            </Button>
            <Button
              type="button"
              variant="outline"
              className="h-10 min-w-[5.5rem]"
              disabled={busy || !activeHotspot?.title}
              onClick={() =>
                activeHotspot?.title &&
                void onExcludeHotspot(
                  activeHotspot.core_topic || activeHotspot.title,
                )
              }
            >
              不喜欢
            </Button>
            <Button
              type="button"
              className="h-10 min-w-[5.5rem]"
              disabled={busy || !activeHotspot}
              onClick={() => {
                if (!activeHotspot) return
                setScriptSeedHotspots([activeHotspot])
                setActiveHotspot(null)
                setScriptOpen(true)
              }}
            >
              生成口播稿
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={!!activeScript}
        onOpenChange={(o) => {
          if (!o) {
            setActiveScript(null)
            setRegenComment('')
          }
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{activeScript?.title || '口播稿'}</DialogTitle>
          </DialogHeader>
          <pre className="bg-muted max-h-[40vh] overflow-auto whitespace-pre-wrap rounded-lg p-3 text-sm leading-relaxed">
            {activeScript?.script}
          </pre>
          <div className="space-y-1.5">
            <Label htmlFor="regen-comment">重新生成意见（可选）</Label>
            <textarea
              id="regen-comment"
              className="min-h-20 w-full rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] px-3 py-2 text-sm"
              placeholder="例如：更口语、少堆砌政策、加一个家长共鸣开场…"
              value={regenComment}
              onChange={(e) => setRegenComment(e.target.value)}
            />
          </div>
          <DialogFooter className="flex-wrap gap-2 sm:justify-end">
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                if (activeScript?.script) {
                  void navigator.clipboard.writeText(activeScript.script)
                  setHint('已复制口播')
                }
              }}
            >
              复制
            </Button>
            <Button
              type="button"
              disabled={busy}
              onClick={() => void onRegenScript()}
            >
              重新生成
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={styleEditOpen} onOpenChange={setStyleEditOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>手改 · {creatorId}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>人设</Label>
              <Input
                value={styleDraft.persona || ''}
                onChange={(e) => setStyleDraft({ ...styleDraft, persona: e.target.value })}
              />
            </div>
            <div>
              <Label>口头禅（逗号分隔）</Label>
              <Input
                value={(styleDraft.catchphrases || []).join('，')}
                onChange={(e) =>
                  setStyleDraft({
                    ...styleDraft,
                    catchphrases: e.target.value
                      .split(/[,，]/)
                      .map((x) => x.trim())
                      .filter(Boolean),
                  })
                }
              />
            </div>
            <div>
              <Label>禁说（逗号分隔）</Label>
              <Input
                value={(styleDraft.taboos || []).join('，')}
                onChange={(e) =>
                  setStyleDraft({
                    ...styleDraft,
                    taboos: e.target.value
                      .split(/[,，]/)
                      .map((x) => x.trim())
                      .filter(Boolean),
                  })
                }
              />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setStyleEditOpen(false)}>
              取消
            </Button>
            <Button type="button" disabled={busy} onClick={() => void saveStyleDraft()}>
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
