/**
 * Task 47 — Content ops studio.
 * Company profile ≠ creator style upload (separate button, re-parse each time).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  digHotspots,
  generateScript,
  getOrgProfile,
  listArtifacts,
  listOfferings,
  listStyles,
  putOrgProfile,
  uploadStyleSpeech,
  upsertStyle,
  type ContentStyle,
  type HotspotItem,
  type Offering,
} from '@/api/contentOps'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

const WF_ACCENT: Record<string, string> = {
  'hotspot.dig': 'border-l-amber-500 bg-amber-500/5',
  'script.gen': 'border-l-rose-500 bg-rose-500/5',
}

export default function ContentStudioPage() {
  const [offerings, setOfferings] = useState<Offering[]>([])
  const [styles, setStyles] = useState<ContentStyle[]>([])
  const [creatorId, setCreatorId] = useState('default')
  const [newCreatorId, setNewCreatorId] = useState('')
  const [orgName, setOrgName] = useState('')
  const [orgFocus, setOrgFocus] = useState('')
  const [orgAudience, setOrgAudience] = useState('')
  const [hotspots, setHotspots] = useState<HotspotItem[]>([])
  const [script, setScript] = useState('')
  const [artifacts, setArtifacts] = useState<
    Array<{ id: string; kind: string; title: string; created_at?: string }>
  >([])
  const [hint, setHint] = useState('')
  const [busy, setBusy] = useState(false)

  const [hotspotOpen, setHotspotOpen] = useState(false)
  const [keywords, setKeywords] = useState('')
  const [pasteText, setPasteText] = useState('')
  const [adapter, setAdapter] = useState<'topic_agent' | 'paste' | 'seed'>('topic_agent')

  const [scriptOpen, setScriptOpen] = useState(false)
  const [duration, setDuration] = useState(60)

  const [styleEditOpen, setStyleEditOpen] = useState(false)
  const [styleDraft, setStyleDraft] = useState<ContentStyle>({})
  const fileRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(async () => {
    try {
      const [o, s, a, p] = await Promise.all([
        listOfferings('content_growth'),
        listStyles(),
        listArtifacts(),
        getOrgProfile(),
      ])
      setOfferings(o.items || [])
      setStyles(s.items || [])
      setArtifacts(
        (a.items || []).map((x) => ({
          id: x.id,
          kind: x.kind,
          title: x.title,
          created_at: x.created_at,
        })),
      )
      const profile = p.profile || {}
      setOrgName(String(profile.name || ''))
      setOrgFocus(String(profile.product_focus || profile.productFocus || ''))
      setOrgAudience(String(profile.target_audience || profile.targetAudience || ''))
    } catch (e) {
      setHint(formatApiError(e))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const activeStyle = styles.find((s) => s.creator_id === creatorId)

  const onOfferingClick = (off: Offering) => {
    if (off.status !== 'implemented') {
      setHint(`「${off.name}」尚未实现 — 占位空态`)
      return
    }
    if (off.target_id === 'hotspot.dig') setHotspotOpen(true)
    else if (off.target_id === 'script.gen') setScriptOpen(true)
  }

  const runDig = async () => {
    setBusy(true)
    setHint('')
    try {
      const r = await digHotspots({
        adapter,
        keywords: keywords || undefined,
        paste_text: adapter === 'paste' ? pasteText : undefined,
        save: true,
      })
      setHotspots(r.items || [])
      setHotspotOpen(false)
      setHint(`已挖掘 ${r.count} 条热点`)
      await refresh()
    } catch (e) {
      setHint(formatApiError(e))
    } finally {
      setBusy(false)
    }
  }

  const runScript = async () => {
    setBusy(true)
    setHint('')
    try {
      const r = await generateScript({
        creator_id: creatorId,
        hotspots,
        duration_sec: duration,
        save: true,
      })
      setScript(r.script || '')
      setScriptOpen(false)
      setHint(
        r.style_is_default
          ? `口播已生成（主讲「${creatorId}」暂无专属风格，用了默认）`
          : '口播已生成',
      )
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
        industry: '教育培训',
        product_focus: orgFocus,
        target_audience: orgAudience,
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
    <div className="mx-auto max-w-6xl space-y-6 pb-10">
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
              手动热点 · 按主讲人设写口播。公司资料走知识库；风格演讲稿用独立上传，每人一波、每次重解析。
            </p>
          </div>
          <Link
            to="/knowledge"
            className="text-sky-200 hover:text-white text-sm underline-offset-4 hover:underline"
          >
            公司资料 → 知识库 RAG
          </Link>
        </div>
        {hint ? (
          <p className="relative mt-4 rounded-lg bg-white/10 px-3 py-2 text-xs text-sky-50">
            {hint}
          </p>
        ) : null}
      </section>

      <div className="grid gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
        {/* Workflow rail */}
        <aside className="space-y-3">
          <h2 className="text-muted-foreground px-1 text-xs font-semibold tracking-wide uppercase">
            常用工作流
          </h2>
          {offerings.map((off) => (
            <button
              key={off.id}
              type="button"
              onClick={() => onOfferingClick(off)}
              className={cn(
                'w-full rounded-xl border border-border border-l-4 p-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md',
                WF_ACCENT[off.target_id] || 'border-l-slate-400 bg-card',
                off.status !== 'implemented' && 'opacity-60',
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{off.name}</span>
                <Badge variant="secondary" className="text-[10px]">
                  {off.status === 'implemented' ? '可用' : '占位'}
                </Badge>
              </div>
              <p className="text-muted-foreground mt-1 text-xs leading-relaxed">
                {off.description}
              </p>
            </button>
          ))}
        </aside>

        <div className="space-y-6">
          {/* Org */}
          <section className="rounded-xl border border-border bg-card p-5 shadow-sm">
            <div className="mb-4 flex items-baseline justify-between">
              <div>
                <h2 className="text-base font-semibold">机构画像</h2>
                <p className="text-muted-foreground text-xs">
                  内容域边界（说哪家的事）。产品册/课件等公司资料请去知识库上传。
                </p>
              </div>
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
              <h2 className="text-base font-semibold">主讲风格（按人）</h2>
              <p className="text-muted-foreground text-xs">
                小A / 小B 各有一条风格。上传演讲稿只更新当前主讲，并<strong>每次重新解析</strong>
                。与知识库公司资料无关。
              </p>
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
                <p className="text-muted-foreground text-sm">点左侧「抓取相关热点」</p>
              ) : (
                <ul className="max-h-64 space-y-2 overflow-auto">
                  {hotspots.map((h, i) => (
                    <li
                      key={`${h.title}-${i}`}
                      className="rounded-lg border border-border/80 bg-background px-3 py-2"
                    >
                      <div className="text-sm font-medium">{h.title}</div>
                      <div className="text-muted-foreground text-xs">{h.summary}</div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="rounded-xl border border-border bg-card p-5 shadow-sm">
              <h2 className="mb-3 text-base font-semibold">口播稿</h2>
              {script ? (
                <pre className="bg-muted max-h-64 overflow-auto whitespace-pre-wrap rounded-lg p-3 text-sm leading-relaxed">
                  {script}
                </pre>
              ) : (
                <p className="text-muted-foreground text-sm">点左侧「生成口播稿」</p>
              )}
            </section>
          </div>

          <section className="rounded-xl border border-border bg-card p-5 shadow-sm">
            <h2 className="mb-3 text-base font-semibold">内容库</h2>
            {artifacts.length === 0 ? (
              <p className="text-muted-foreground text-sm">暂无产物</p>
            ) : (
              <div className="divide-y divide-border">
                {artifacts.slice(0, 15).map((a) => (
                  <div
                    key={a.id}
                    className="flex items-center justify-between gap-3 py-2 text-sm"
                  >
                    <span className="min-w-0 truncate">
                      <Badge variant="outline" className="mr-2">
                        {a.kind}
                      </Badge>
                      {a.title}
                    </span>
                    <span className="text-muted-foreground shrink-0 text-xs">
                      {a.created_at}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>

      {/* Dialogs */}
      <Dialog open={hotspotOpen} onOpenChange={setHotspotOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>抓取相关热点</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2">
              {(['topic_agent', 'paste', 'seed'] as const).map((a) => (
                <Button
                  key={a}
                  type="button"
                  size="sm"
                  variant={adapter === a ? 'default' : 'outline'}
                  onClick={() => setAdapter(a)}
                >
                  {a}
                </Button>
              ))}
            </div>
            <div>
              <Label htmlFor="kw">关键字</Label>
              <Input id="kw" value={keywords} onChange={(e) => setKeywords(e.target.value)} />
            </div>
            {adapter === 'paste' ? (
              <textarea
                className="border-input bg-background min-h-24 w-full rounded-md border p-2 text-sm"
                placeholder="每行一条热点"
                value={pasteText}
                onChange={(e) => setPasteText(e.target.value)}
              />
            ) : null}
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setHotspotOpen(false)}>
              取消
            </Button>
            <Button type="button" disabled={busy} onClick={() => void runDig()}>
              开始挖掘
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={scriptOpen} onOpenChange={setScriptOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>生成口播稿</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <p className="text-muted-foreground text-xs">
              使用主讲 <strong>{creatorId}</strong>
              {activeStyle ? ' 的专属风格' : '（无专属则默认风格）'} · 热点{' '}
              {hotspots.length} 条
            </p>
            <div>
              <Label htmlFor="dur">时长（秒）</Label>
              <Input
                id="dur"
                type="number"
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value) || 60)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setScriptOpen(false)}>
              取消
            </Button>
            <Button type="button" disabled={busy} onClick={() => void runScript()}>
              生成
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
