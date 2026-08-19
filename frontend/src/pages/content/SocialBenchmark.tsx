/**
 * Task 52 S4 — Social benchmark UI.
 * Flow: probe card → start analysis (poll) → results + export / replica stub.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  exportSocialXlsx,
  getSocialTask,
  listSocialContents,
  listSocialFollows,
  probeSocialAccount,
  replicaSocialBatch,
  retrySocialTask,
  startSocialAnalysis,
  type SocialAccountCard,
  type SocialContent,
  type SocialResultRow,
  type SocialTask,
} from '@/api/social'
import { formatApiError } from '@/api/http'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'

const PLATFORMS = [
  { value: 'douyin', label: '抖音', open: true },
  { value: 'wechat_channels', label: '视频号', open: false },
  { value: 'wechat_mp', label: '公众号', open: false },
  { value: 'xiaohongshu', label: '小红书', open: false },
] as const

function fmtCount(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n >= 10_000) return `${(n / 10_000).toFixed(1)}万`
  return String(n)
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return iso.replace('T', ' ').slice(0, 19)
}

function asText(v: unknown): string {
  return typeof v === 'string' ? v.trim() : ''
}

function AnalysisView({ structure }: { structure: Record<string, unknown> }) {
  const golden = asText(structure.golden_hook)
  const attraction = asText(structure.attraction)
  const story = asText(structure.storytelling)
  const logic = asText(structure.logic)
  const hasNarrative = Boolean(golden || attraction || story || logic)
  const hooks = Array.isArray(structure.hooks) ? structure.hooks.map(String) : []
  const outline = Array.isArray(structure.outline) ? structure.outline : []
  const roleLabel: Record<string, string> = {
    hook: '钩子',
    pain: '痛点',
    method: '方法',
    cta: '收束',
    other: '过渡',
  }

  return (
    <div className="space-y-3 text-sm leading-relaxed text-[#0F172A]">
      {hasNarrative ? (
        <>
          {golden ? (
            <div>
              <div className="text-xs font-semibold text-[#64748B]">黄金钩子</div>
              <p className="mt-1 whitespace-pre-wrap">{golden}</p>
            </div>
          ) : null}
          {attraction ? (
            <div>
              <div className="text-xs font-semibold text-[#64748B]">怎么吸引人</div>
              <p className="mt-1 whitespace-pre-wrap">{attraction}</p>
            </div>
          ) : null}
          {story ? (
            <div>
              <div className="text-xs font-semibold text-[#64748B]">怎么讲故事</div>
              <p className="mt-1 whitespace-pre-wrap">{story}</p>
            </div>
          ) : null}
          {logic ? (
            <div>
              <div className="text-xs font-semibold text-[#64748B]">语言逻辑结构</div>
              <p className="mt-1 whitespace-pre-wrap">{logic}</p>
            </div>
          ) : null}
        </>
      ) : (
        <>
          {hooks.length ? (
            <div>
              <div className="text-xs font-semibold text-[#64748B]">黄金钩子</div>
              <p className="mt-1">{hooks.join('；')}</p>
            </div>
          ) : null}
          {outline.length ? (
            <div>
              <div className="text-xs font-semibold text-[#64748B]">语言逻辑结构</div>
              <ol className="mt-1 list-decimal space-y-1 pl-4">
                {outline.map((item, i) => {
                  const row = item as { role?: string; text?: string }
                  const label = roleLabel[String(row.role || '')] || '段落'
                  return (
                    <li key={i}>
                      <span className="text-[#64748B]">{label}：</span>
                      {String(row.text || item)}
                    </li>
                  )
                })}
              </ol>
            </div>
          ) : (
            <p className="text-[#94A3B8]">本条还没有口播结构拆解，请点「结构分析」。</p>
          )}
        </>
      )}
    </div>
  )
}

function CreatorCard({
  account,
  compact = false,
}: {
  account: SocialAccountCard
  compact?: boolean
}) {
  const size = compact ? 'size-9 text-sm' : 'size-14 text-lg'
  return (
    <div className={cn('flex items-center gap-3', compact ? '' : 'flex-wrap gap-4')}>
      {account.avatar_url ? (
        <img
          src={account.avatar_url}
          alt=""
          className={cn(size, 'shrink-0 rounded-full object-cover')}
        />
      ) : (
        <div
          className={cn(
            size,
            'flex shrink-0 items-center justify-center rounded-full bg-[#E2E8F0] font-semibold',
          )}
        >
          {(account.nickname || account.account_key || '?').slice(0, 1)}
        </div>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate font-semibold">{account.nickname || '—'}</span>
          <Badge variant="secondary">{account.account_key}</Badge>
        </div>
        {!compact ? (
          <div className="mt-1 flex flex-wrap gap-3 text-sm text-[#64748B]">
            <span>粉丝 {fmtCount(account.follower_count)}</span>
            <span>获赞 {fmtCount(account.total_favorited)}</span>
            <span>内容 {fmtCount(account.content_count)}</span>
          </div>
        ) : (
          <div className="truncate text-xs text-[#64748B]">
            粉丝 {fmtCount(account.follower_count)}
          </div>
        )}
      </div>
    </div>
  )
}

function progressLabel(task: SocialTask): string {
  const stage = task.stage
  const n = task.total_count || 0
  const neu = task.new_count || 0
  if (stage === 'failed' || task.status === 'failed') return '失败'
  if (stage === 'fetching') {
    if (n > 0) return `已拉到 ${n} 条，正在落库`
    return '正在拉取内容'
  }
  if (stage === 'fetched') return `已入库 ${n} 条（新增 ${neu}），待结构分析`
  if (stage === 'analyzing') {
    const rc = task.result_count || 0
    return n > 0 ? `口播结构分析 ${rc}/${n}` : '口播结构分析中'
  }
  if (stage === 'analyzed') return `结构分析完成 · ${task.result_count || n} 条`
  if (task.status === 'done') return '完成'
  if (task.progress < 10) return '排队中'
  return `${task.progress}%`
}

function Stepper({
  account,
  contentsLen,
  task,
}: {
  account: SocialAccountCard | null
  contentsLen: number
  task: SocialTask | null
}) {
  const stage = task?.stage
  const n = task?.total_count || contentsLen
  const neu = task?.new_count || 0
  const rc = task?.result_count || 0
  const s1 = account ? 'done' : 'idle'
  const s2 =
    stage === 'fetching'
      ? 'active'
      : stage === 'fetched' || stage === 'analyzing' || stage === 'analyzed' || contentsLen > 0
        ? 'done'
        : 'idle'
  const s3 =
    stage === 'analyzing' ? 'active' : stage === 'analyzed' ? 'done' : 'idle'
  const items = [
    {
      key: '1',
      title: '确认账号',
      state: s1,
      detail: account ? `${account.nickname || account.account_key} 已关注` : '从左侧添加或选择 UP 主',
    },
    {
      key: '2',
      title: '内容落库',
      state: s2,
      detail:
        stage === 'fetching' && n > 0
          ? `已拉到 ${n} 条，写入中`
          : stage === 'fetching'
            ? '请求最近内容'
            : n > 0 || contentsLen > 0
              ? `已入库 ${contentsLen || n} 条${neu ? `（本轮新增 ${neu}）` : ''}`
              : '拉取后即可点选看全文',
    },
    {
      key: '3',
      title: '口播结构分析',
      state: s3,
      detail:
        stage === 'analyzing'
          ? n > 0
            ? `${rc}/${n}`
            : '分析中'
          : stage === 'analyzed'
            ? `已完成 ${rc || n} 条`
            : '入库后再点「结构分析」',
    },
  ] as const
  return (
    <ol className="mt-4 grid gap-2 md:grid-cols-3">
      {items.map((it, i) => (
        <li
          key={it.key}
          className={cn(
            'rounded-lg border px-3 py-2 text-sm',
            it.state === 'done' && 'border-[#86EFAC] bg-[#F0FDF4]',
            it.state === 'active' && 'border-[#93C5FD] bg-[#EFF6FF]',
            it.state === 'idle' && 'border-[#E2E8F0] bg-[#F8FAFC]',
          )}
        >
          <div className="text-xs text-[#64748B]">
            {i + 1}. {it.title}
          </div>
          <div className="mt-0.5 font-medium text-[#0F172A]">{it.detail}</div>
        </li>
      ))}
    </ol>
  )
}

function hasFullText(c: SocialContent): boolean {
  return Boolean(c.content && c.content.trim().length > 0)
}

export default function SocialBenchmarkPage() {
  const [platform, setPlatform] = useState('douyin')
  const [accountKey, setAccountKey] = useState('')
  const [follows, setFollows] = useState<SocialAccountCard[]>([])
  const [account, setAccount] = useState<SocialAccountCard | null>(null)
  const [task, setTask] = useState<SocialTask | null>(null)
  const [viewTaskId, setViewTaskId] = useState<number | null>(null)
  const [resultsByContent, setResultsByContent] = useState<
    Record<number, SocialResultRow>
  >({})
  const [contents, setContents] = useState<SocialContent[]>([])
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [activeId, setActiveId] = useState<number | null>(null)
  const [hint, setHint] = useState('')
  const [busy, setBusy] = useState(false)
  const [replicaPreview, setReplicaPreview] = useState<string>('')
  const [addOpen, setAddOpen] = useState(false)
  const [fetchOpen, setFetchOpen] = useState(false)
  const [fetchCount, setFetchCount] = useState('20')

  // session-local filters (spec: no cloud presets)
  const [likeMin, setLikeMin] = useState('')
  const [collectMin, setCollectMin] = useState('')
  const [durationMin, setDurationMin] = useState('')
  const [durationMax, setDurationMax] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [hasContent, setHasContent] = useState<'all' | 'yes' | 'no'>('all')

  const pollRef = useRef<number | null>(null)

  const stopPoll = useCallback(() => {
    if (pollRef.current != null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  useEffect(() => () => stopPoll(), [stopPoll])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const res = await listSocialFollows()
        if (cancelled) return
        const items = res.items || []
        setFollows(items)
        if (items[0]) {
          setAccount(items[0])
          const data = await listSocialContents({ account_id: items[0].id })
          if (!cancelled) setContents(data.items || [])
        }
      } catch (e) {
        if (!cancelled) setHint(formatApiError(e))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const applyTaskPayload = useCallback((t: SocialTask) => {
    setTask(t)
    const map: Record<number, SocialResultRow> = {}
    for (const r of t.results || []) {
      map[r.content_id] = r
    }
    setResultsByContent(map)
  }, [])

  const loadContents = useCallback(async (accountId: number) => {
    const params: Parameters<typeof listSocialContents>[0] = {
      account_id: accountId,
    }
    if (likeMin.trim()) params.like_min = Number(likeMin)
    if (collectMin.trim()) params.collect_min = Number(collectMin)
    if (durationMin.trim()) params.duration_min = Number(durationMin)
    if (durationMax.trim()) params.duration_max = Number(durationMax)
    if (dateFrom) params.date_from = dateFrom
    if (dateTo) params.date_to = dateTo
    if (hasContent === 'yes') params.has_content = true
    if (hasContent === 'no') params.has_content = false
    const res = await listSocialContents(params)
    setContents(res.items || [])
  }, [likeMin, collectMin, durationMin, durationMax, dateFrom, dateTo, hasContent])

  const loadTask = useCallback(
    async (taskId: number) => {
      const t = await getSocialTask(taskId)
      applyTaskPayload(t)
      setViewTaskId(taskId)
      if ((t.progress || 0) >= 40 && account?.id) {
        await loadContents(account.id)
      }
      if (t.status === 'done' || t.status === 'failed') {
        stopPoll()
        if (t.status === 'done' && account?.id) {
          await loadContents(account.id)
          if (t.stage === 'fetched') {
            setHint(
              `已入库 ${t.total_count} 条（新增 ${t.new_count}）。点选可看全文，再点「结构分析」。`,
            )
          } else if (t.stage === 'analyzed') {
            setHint(`口播结构分析完成 ${t.result_count ?? t.total_count} 条。`)
          } else if ((t.new_count || 0) === 0 && t.hint_previous_task_id) {
            setHint(
              `本次无新增内容。可查看上次分析结果 #${t.hint_previous_task_id}`,
            )
          }
        }
      }
      return t
    },
    [account?.id, applyTaskPayload, loadContents, stopPoll],
  )

  const startPoll = useCallback(
    (taskId: number) => {
      stopPoll()
      void loadTask(taskId)
      pollRef.current = window.setInterval(() => {
        void loadTask(taskId)
      }, 1500)
    },
    [loadTask, stopPoll],
  )

  const onSelectFollow = async (card: SocialAccountCard) => {
    if (account?.id === card.id) return
    stopPoll()
    setAccount(card)
    setTask(null)
    setViewTaskId(null)
    setSelected(new Set())
    setActiveId(null)
    setResultsByContent({})
    setReplicaPreview('')
    setHint('')
    setBusy(true)
    try {
      await loadContents(card.id)
    } catch (e) {
      setHint(formatApiError(e))
    } finally {
      setBusy(false)
    }
  }

  const onProbe = async () => {
    setHint('')
    setBusy(true)
    try {
      const card = await probeSocialAccount({
        platform,
        account_key: accountKey.trim(),
      })
      const listed = await listSocialFollows()
      setFollows(listed.items || [])
      setAccount(card)
      setTask(null)
      setViewTaskId(null)
      setSelected(new Set())
      setActiveId(null)
      setResultsByContent({})
      await loadContents(card.id)
      setAddOpen(false)
      setAccountKey('')
      setHint('已加入关注。点「拉取内容」选择条数后再入库。')
    } catch (e) {
      setHint(formatApiError(e))
    } finally {
      setBusy(false)
    }
  }

  const clampFetchCount = () => {
    const n = Number(fetchCount)
    if (!Number.isFinite(n) || n <= 0) return 20
    return Math.max(1, Math.min(50, Math.round(n)))
  }

  const enqueuePhase = async (phase: 'fetch' | 'analyze', fetchLimit?: number) => {
    if (!account) {
      setHint('请先添加并选中 UP 主')
      return
    }
    setHint('')
    setBusy(true)
    try {
      const t = await startSocialAnalysis({
        platform: account.platform,
        account_key: account.account_key,
        phase,
        fetch_limit: fetchLimit,
      })
      applyTaskPayload(t)
      setViewTaskId(t.id)
      if (t.status === 'pending' || t.status === 'running') {
        startPoll(t.id)
        setHint(
          t.created === false
            ? '已有进行中的任务，继续跟踪进度'
            : phase === 'fetch'
              ? `正在拉取近 ${fetchLimit ?? 20} 条并落库…`
              : '正在做口播结构分析…',
        )
      } else if (t.status === 'done') {
        await loadContents(account.id)
      }
    } catch (e) {
      setHint(formatApiError(e))
    } finally {
      setBusy(false)
    }
  }

  const onConfirmFetch = async () => {
    const n = clampFetchCount()
    setFetchCount(String(n))
    setFetchOpen(false)
    await enqueuePhase('fetch', n)
  }

  const onRetry = async () => {
    if (!task) return
    setBusy(true)
    try {
      const t = await retrySocialTask(task.id)
      applyTaskPayload(t)
      startPoll(t.id)
      setHint('已重新入队')
    } catch (e) {
      setHint(formatApiError(e))
    } finally {
      setBusy(false)
    }
  }

  const onExport = async () => {
    const id = viewTaskId || task?.id
    if (!id) {
      setHint('请先完成分析')
      return
    }
    setBusy(true)
    try {
      await exportSocialXlsx(id)
      setHint('Excel 已下载')
    } catch (e) {
      setHint(formatApiError(e))
    } finally {
      setBusy(false)
    }
  }

  const onReplica = async () => {
    const id = viewTaskId || task?.id
    if (!id) {
      setHint('请先完成分析')
      return
    }
    const ids = selected.size > 0 ? [...selected] : activeId != null ? [activeId] : []
    if (ids.length === 0) {
      setHint('请先勾选或点选要复刻的内容')
      return
    }
    if (ids.length > 10) {
      setHint('单次复刻最多 10 条')
      return
    }
    setBusy(true)
    try {
      const res = await replicaSocialBatch({ content_ids: ids, task_id: id })
      const lines: string[] = []
      for (const item of res.items) {
        const r = item.replica
        lines.push(
          `#${item.content_id}\n标题: ${(r.titles || []).join(' | ')}\n${r.script || ''}\n标签: ${(r.tags || []).map((t) => `#${t}`).join(' ')}`,
        )
        setResultsByContent((prev) => ({
          ...prev,
          [item.content_id]: {
            ...(prev[item.content_id] || { content_id: item.content_id }),
            replica_json: r as Record<string, unknown>,
          },
        }))
      }
      setReplicaPreview(lines.join('\n\n---\n\n'))
      setHint(
        '复刻稿已生成（模版套品牌；LLM 不可用时会降级占位稿）。',
      )
    } catch (e) {
      setHint(formatApiError(e))
    } finally {
      setBusy(false)
    }
  }

  const onOpenPrevious = async () => {
    const prev = task?.hint_previous_task_id
    if (!prev || !account) return
    setBusy(true)
    try {
      await loadTask(prev)
      await loadContents(account.id)
      setHint(`已切换到上次任务 #${prev}`)
    } catch (e) {
      setHint(formatApiError(e))
    } finally {
      setBusy(false)
    }
  }

  const active = useMemo(
    () => contents.find((c) => c.id === activeId) || null,
    [contents, activeId],
  )
  const activeResult = activeId != null ? resultsByContent[activeId] : undefined
  const structure = (activeResult?.structure_json || null) as Record<
    string,
    unknown
  > | null

  const toggleSelect = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const analyzing =
    task != null && (task.status === 'pending' || task.status === 'running')

  return (
    <div className="mx-auto flex h-full max-w-7xl flex-col gap-4 p-4 md:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">社媒对标</h1>
          <p className="mt-1 text-sm text-[#64748B]">
            关注 UP 主 → 拉取内容落库 → 再做口播结构分析
          </p>
        </div>
        {hint ? (
          <p className="max-w-xl text-right text-sm text-[#0F172A]">{hint}</p>
        ) : null}
      </div>

      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[16rem_1fr]">
        <aside className="flex min-h-[28rem] flex-col rounded-xl border border-[#E2E8F0] bg-white shadow-sm">
          <div className="flex items-center justify-between gap-2 border-b border-[#E2E8F0] p-3">
            <h2 className="text-sm font-semibold">关注的 UP 主</h2>
            <Button
              size="sm"
              variant="secondary"
              disabled={busy || analyzing}
              onClick={() => setAddOpen(true)}
            >
              添加关注
            </Button>
          </div>
          <div className="min-h-0 flex-1 overflow-auto p-2">
            {follows.length === 0 ? (
              <p className="px-2 py-8 text-center text-sm text-[#94A3B8]">
                还没有关注。点「添加关注」用抖音号确认账号。
              </p>
            ) : (
              <ul className="space-y-1">
                {follows.map((f) => (
                  <li key={f.id}>
                    <button
                      type="button"
                      className={cn(
                        'w-full rounded-lg px-2 py-2 text-left hover:bg-[#F8FAFC]',
                        account?.id === f.id && 'bg-[#EFF6FF]',
                      )}
                      onClick={() => void onSelectFollow(f)}
                    >
                      <CreatorCard account={f} compact />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>

        <div className="flex min-h-0 flex-col gap-4">
      <section className="rounded-xl border border-[#E2E8F0] bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            disabled={busy || analyzing || !account}
            onClick={() => {
              setFetchCount('20')
              setFetchOpen(true)
            }}
          >
            拉取内容
          </Button>
          <Button
            variant="secondary"
            disabled={busy || analyzing || !account || contents.length === 0}
            onClick={() => void enqueuePhase('analyze')}
          >
            结构分析
          </Button>
        </div>

        <Stepper account={account} contentsLen={contents.length} task={task} />

        {account ? (
          <div className="mt-4 rounded-lg bg-[#F8FAFC] p-3">
            <CreatorCard account={account} />
          </div>
        ) : null}

        {task ? (
          <div className="mt-4 space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span>
                任务 #{task.id} · {progressLabel(task)}
                {task.progress != null &&
                task.stage !== 'fetched' &&
                task.stage !== 'analyzed'
                  ? ` · ${task.progress}%`
                  : ''}
              </span>
              <div className="flex gap-2">
                {task.status === 'failed' ? (
                  <Button size="sm" variant="outline" disabled={busy} onClick={() => void onRetry()}>
                    重试
                  </Button>
                ) : null}
                {task.hint_previous_task_id ? (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => void onOpenPrevious()}
                  >
                    打开上次结果
                  </Button>
                ) : null}
              </div>
            </div>
            <Progress value={Math.min(100, Math.max(0, task.progress))} />
            {task.status === 'failed' && task.error ? (
              <p className="text-sm text-red-600">{task.error}</p>
            ) : null}
          </div>
        ) : null}
      </section>

      {/* Step 3: list + detail */}
      <section className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="flex min-h-[28rem] flex-col rounded-xl border border-[#E2E8F0] bg-white shadow-sm">
          <div className="flex flex-wrap items-center gap-2 border-b border-[#E2E8F0] p-3">
            <Input
              className="h-8 w-24"
              placeholder="赞≥"
              value={likeMin}
              onChange={(e) => setLikeMin(e.target.value)}
            />
            <Input
              className="h-8 w-24"
              placeholder="藏≥"
              value={collectMin}
              onChange={(e) => setCollectMin(e.target.value)}
            />
            <Input
              className="h-8 w-20"
              placeholder="时长≥"
              value={durationMin}
              onChange={(e) => setDurationMin(e.target.value)}
            />
            <Input
              className="h-8 w-20"
              placeholder="时长≤"
              value={durationMax}
              onChange={(e) => setDurationMax(e.target.value)}
            />
            <Input
              className="h-8 w-36"
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
            />
            <Input
              className="h-8 w-36"
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
            />
            <select
              className="h-8 rounded-md border border-[#E2E8F0] px-2 text-sm"
              value={hasContent}
              onChange={(e) =>
                setHasContent(e.target.value as 'all' | 'yes' | 'no')
              }
            >
              <option value="all">全文不限</option>
              <option value="yes">有全文</option>
              <option value="no">无全文</option>
            </select>
            <Button
              size="sm"
              variant="secondary"
              disabled={!account || busy}
              onClick={() => account && void loadContents(account.id)}
            >
              筛选
            </Button>
            <div className="ml-auto flex gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={busy || !(viewTaskId || task?.id)}
                onClick={() => void onExport()}
              >
                导出 Excel
              </Button>
              <Button size="sm" disabled={busy} onClick={() => void onReplica()}>
                复刻
              </Button>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-[#F8FAFC] text-[#64748B]">
                <tr>
                  <th className="px-2 py-2 font-medium">选</th>
                  <th className="px-2 py-2 font-medium">标题</th>
                  <th className="px-2 py-2 font-medium">时长</th>
                  <th className="px-2 py-2 font-medium">赞</th>
                  <th className="px-2 py-2 font-medium">藏</th>
                  <th className="px-2 py-2 font-medium">转</th>
                  <th className="px-2 py-2 font-medium">评</th>
                  <th className="px-2 py-2 font-medium">发布</th>
                  <th className="px-2 py-2 font-medium">全文</th>
                </tr>
              </thead>
              <tbody>
                {contents.map((c) => (
                  <tr
                    key={c.id}
                    className={cn(
                      'cursor-pointer border-t border-[#F1F5F9] hover:bg-[#F8FAFC]',
                      activeId === c.id && 'bg-[#EFF6FF]',
                    )}
                    onClick={() => setActiveId(c.id)}
                  >
                    <td className="px-2 py-2" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selected.has(c.id)}
                        onChange={() => toggleSelect(c.id)}
                      />
                    </td>
                    <td className="max-w-[14rem] truncate px-2 py-2">
                      {c.title || c.external_id}
                    </td>
                    <td className="px-2 py-2">{c.duration_s ?? '—'}</td>
                    <td className="px-2 py-2">{fmtCount(c.like_count)}</td>
                    <td className="px-2 py-2">{fmtCount(c.collect_count)}</td>
                    <td className="px-2 py-2">{fmtCount(c.share_count)}</td>
                    <td className="px-2 py-2">{fmtCount(c.comment_count)}</td>
                    <td className="whitespace-nowrap px-2 py-2 text-xs text-[#64748B]">
                      {c.published_at?.slice(0, 10) || '—'}
                    </td>
                    <td className="px-2 py-2">
                      {hasFullText(c) ? (
                        <Badge>有</Badge>
                      ) : (
                        <Badge variant="secondary">无</Badge>
                      )}
                    </td>
                  </tr>
                ))}
                {contents.length === 0 ? (
                  <tr>
                    <td
                      colSpan={9}
                      className="px-3 py-10 text-center text-[#94A3B8]"
                    >
                      {account
                        ? '暂无入库内容。点「拉取内容」，确认条数后再入库。'
                        : '从左侧选择或添加 UP 主'}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </div>

        <div className="flex min-h-[28rem] flex-col gap-3 rounded-xl border border-[#E2E8F0] bg-white p-4 shadow-sm">
          <h2 className="text-sm font-semibold">详情</h2>
          {!active ? (
            <p className="text-sm text-[#94A3B8]">点选左侧一行查看完整文稿与口播结构</p>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto">
              <div>
                <h3 className="text-base font-semibold leading-snug">
                  {active.title || active.external_id}
                </h3>
                <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-[#64748B]">
                  <span>时长 {active.duration_s ?? '—'}s</span>
                  <span>赞 {fmtCount(active.like_count)}</span>
                  <span>藏 {fmtCount(active.collect_count)}</span>
                  <span>转 {fmtCount(active.share_count)}</span>
                  <span>评 {fmtCount(active.comment_count)}</span>
                  <span>发布 {fmtTime(active.published_at)}</span>
                  <span>采集 {fmtTime(active.fetched_at)}</span>
                  <span>来源 {active.content_source || '—'}</span>
                  <span>ID {active.external_id}</span>
                </div>
              </div>
              <div className="min-h-[12rem] flex-1">
                <div className="text-xs font-semibold text-[#64748B]">口播全文</div>
                <pre className="mt-1 max-h-[28rem] overflow-auto whitespace-pre-wrap rounded-lg bg-[#F8FAFC] p-3 text-sm leading-7">
                  {active.content || '（无全文）'}
                </pre>
              </div>
              <div>
                <div className="text-xs font-semibold text-[#64748B]">口播结构分析</div>
                <div className="mt-2">
                  {structure ? (
                    <AnalysisView structure={structure} />
                  ) : (
                    <p className="text-sm text-[#94A3B8]">
                      文稿已入库。点「结构分析」后这里会写黄金钩子、吸引手法、叙事和逻辑链。
                    </p>
                  )}
                </div>
              </div>
              {activeResult?.replica_json || replicaPreview ? (
                <div>
                  <div className="text-xs font-semibold text-[#64748B]">复刻稿</div>
                  <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-[#F8FAFC] p-3 text-xs">
                    {replicaPreview ||
                      JSON.stringify(activeResult?.replica_json, null, 2)}
                  </pre>
                </div>
              ) : null}
            </div>
          )}
        </div>
      </section>
        </div>
      </div>

      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>添加关注</DialogTitle>
            <DialogDescription>
              用抖音号确认账号并加入本租户关注列表（不支持链接）。
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <div>
              <Label htmlFor="platform">平台</Label>
              <select
                id="platform"
                className="mt-1 flex h-9 w-full rounded-md border border-[#E2E8F0] bg-white px-2 text-sm"
                value={platform}
                onChange={(e) => setPlatform(e.target.value)}
                disabled={busy || analyzing}
              >
                {PLATFORMS.map((p) => (
                  <option key={p.value} value={p.value} disabled={!p.open}>
                    {p.label}
                    {p.open ? '' : '（暂未开放）'}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <Label htmlFor="account_key">抖音号</Label>
              <Input
                id="account_key"
                className="mt-1"
                placeholder="只支持抖音号，不支持链接"
                value={accountKey}
                onChange={(e) => setAccountKey(e.target.value)}
                disabled={busy || analyzing || platform !== 'douyin'}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddOpen(false)}>
              取消
            </Button>
            <Button
              disabled={busy || analyzing || !accountKey.trim() || platform !== 'douyin'}
              onClick={() => void onProbe()}
            >
              拉取账号
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={fetchOpen} onOpenChange={setFetchOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>拉取内容</DialogTitle>
            <DialogDescription>
              确认目标 UP 主后拉取最近一页并入库，不会自动做结构分析。
            </DialogDescription>
          </DialogHeader>
          {account ? (
            <div className="rounded-lg bg-[#F8FAFC] p-3">
              <CreatorCard account={account} />
            </div>
          ) : (
            <p className="text-sm text-[#94A3B8]">请先选中 UP 主</p>
          )}
          <div>
            <Label htmlFor="fetch_count">最近条数</Label>
            <Input
              id="fetch_count"
              className="mt-1"
              type="number"
              min={1}
              max={50}
              value={fetchCount}
              onChange={(e) => setFetchCount(e.target.value)}
              disabled={busy || analyzing}
            />
            <p className="mt-1 text-xs text-[#64748B]">默认 20 条，最多 50 条。</p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setFetchOpen(false)}>
              取消
            </Button>
            <Button
              disabled={busy || analyzing || !account}
              onClick={() => void onConfirmFetch()}
            >
              确认拉取
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
