/**
 * 知识库 RAG — 工作区页（上传 / 文档管理 / 检索）
 */
import { useCallback, useEffect, useRef, useState, type ChangeEvent } from 'react'

import { formatApiError } from '@/api/http'
import {
  ragAsk,
  ragDeleteDocument,
  ragGetTask,
  ragListDocuments,
  ragRetryTask,
  ragSearch,
  ragStatus,
  ragUploadPdf,
  type RagAskData,
  type RagDocumentItem,
  type RagStatusData,
} from '@/api/rag'
import { ForbiddenBanner } from '@/components/role/RoleSwitcher'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { useAuthStore } from '@/stores/authStore'
import { cn } from '@/lib/utils'

const IN_FLIGHT = new Set(['queued', 'parsing', 'chunking', 'embedding'])

function uploadPhaseLabel(status: string, pct: number): string {
  if (status === 'ready' || pct >= 100) return '入库完成'
  if (status === 'failed') return '处理失败'
  if (status === 'embedding' || pct >= 55) return 'Embedding 向量化中…'
  if (status === 'chunking' || pct >= 35) return '分块中…'
  if (status === 'parsing' || pct >= 15) return '解析 PDF…'
  if (status === 'queued') return '已排队…'
  return '上传文件中…'
}

function statusBadgeVariant(
  status: string | undefined,
): 'success' | 'destructive' | 'warning' | 'outline' {
  if (status === 'ready') return 'success'
  if (status === 'failed') return 'destructive'
  if (status && IN_FLIGHT.has(status)) return 'warning'
  return 'outline'
}

function statusLabel(status: string | undefined): string {
  switch (status) {
    case 'queued':
      return '排队中'
    case 'parsing':
      return '解析中'
    case 'chunking':
      return '分块中'
    case 'embedding':
      return '向量化'
    case 'ready':
      return '就绪'
    case 'failed':
      return '失败'
    default:
      return status || '就绪'
  }
}

export default function RagPanel() {
  const roleEpoch = useAuthStore((s) => s.roleEpoch)
  const [q, setQ] = useState('什么是 NexusAI？')
  const [ask, setAsk] = useState<RagAskData | null>(null)
  const [search, setSearch] = useState<unknown>(null)
  const [stats, setStats] = useState<RagStatusData | null>(null)
  const [docs, setDocs] = useState<RagDocumentItem[]>([])
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadPct, setUploadPct] = useState(0)
  const [uploadStatus, setUploadStatus] = useState('')
  const [pollTaskId, setPollTaskId] = useState<string | null>(null)
  const [err, setErr] = useState('')
  const [hint, setHint] = useState('')
  const [pdfFile, setPdfFile] = useState<File | null>(null)
  const skip = useRef(true)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const loadStatus = useCallback(async () => {
    const r = await ragStatus()
    setStats(r.data)
  }, [])

  const loadDocs = useCallback(async () => {
    const r = await ragListDocuments()
    setDocs(r.data?.items || [])
  }, [])

  const refreshAll = useCallback(async () => {
    try {
      await Promise.all([loadStatus(), loadDocs()])
    } catch (e) {
      setErr(formatApiError(e, 'chat:write'))
    }
  }, [loadDocs, loadStatus])

  useEffect(() => {
    void refreshAll()
  }, [refreshAll])

  useEffect(() => {
    if (skip.current) {
      skip.current = false
      return
    }
    setAsk(null)
    setSearch(null)
    setUploading(false)
    setUploadPct(0)
    setUploadStatus('')
    setPollTaskId(null)
    setHint('')
    setErr('')
    void refreshAll()
  }, [roleEpoch, refreshAll])

  const hasInFlight = docs.some((d) => d.status && IN_FLIGHT.has(d.status))

  useEffect(() => {
    if (!hasInFlight && !pollTaskId) return
    const tick = window.setInterval(() => {
      void loadDocs()
      void loadStatus()
    }, 1500)
    return () => window.clearInterval(tick)
  }, [hasInFlight, pollTaskId, loadDocs, loadStatus])

  useEffect(() => {
    if (!pollTaskId) return
    let cancelled = false
    const run = async () => {
      try {
        const r = await ragGetTask(pollTaskId)
        if (cancelled) return
        const st = r.data?.status || ''
        const pct = Math.round((r.data?.progress ?? 0) * 100)
        setUploadStatus(st)
        setUploadPct(pct)
        if (st === 'ready') {
          setUploading(false)
          setPollTaskId(null)
          setHint('入库完成')
          await loadDocs()
          await loadStatus()
        } else if (st === 'failed') {
          setUploading(false)
          setPollTaskId(null)
          setErr(r.data?.error_code || '处理失败')
          await loadDocs()
        }
      } catch (e) {
        if (!cancelled) setErr(formatApiError(e, 'chat:write'))
      }
    }
    void run()
    const tick = window.setInterval(() => {
      void run()
    }, 1500)
    return () => {
      cancelled = true
      window.clearInterval(tick)
    }
  }, [pollTaskId, loadDocs, loadStatus])

  const onFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null
    setHint('')
    setErr('')
    if (f && !f.name.toLowerCase().endsWith('.pdf')) {
      setPdfFile(null)
      setErr('只支持 PDF 文件（须真实 PDF，勿用 .md 改后缀）')
      if (fileInputRef.current) fileInputRef.current.value = ''
      return
    }
    setPdfFile(f)
  }

  const onUpload = async () => {
    if (!pdfFile) {
      setErr('请先选择 PDF 文件')
      return
    }
    setBusy(true)
    setUploading(true)
    setUploadPct(5)
    setUploadStatus('queued')
    setErr('')
    setHint('')
    try {
      const r = await ragUploadPdf(pdfFile)
      const doc = r.documents?.[0] || r.data
      const taskId = doc?.doc_id || r.task_ids?.[0] || ''
      setHint(r.message || '已排队解析')
      setPdfFile(null)
      if (fileInputRef.current) fileInputRef.current.value = ''
      await refreshAll()
      if (doc?.duplicate && doc.status === 'ready') {
        setUploading(false)
        setUploadPct(100)
        setUploadStatus('ready')
        setPollTaskId(null)
        return
      }
      if (doc?.status === 'failed') {
        setUploading(false)
        setUploadPct(0)
        setPollTaskId(null)
        setErr(doc.duplicate ? '文件已存在（上次失败，可在列表重试）' : '处理失败')
        return
      }
      if (taskId) {
        setPollTaskId(taskId)
        setUploadStatus(doc?.status || 'queued')
      } else {
        setUploading(false)
      }
    } catch (e) {
      setUploading(false)
      setUploadPct(0)
      setPollTaskId(null)
      setErr(formatApiError(e, 'chat:write'))
    } finally {
      setBusy(false)
    }
  }

  const onRetry = async (docId: string, name: string) => {
    setBusy(true)
    setErr('')
    try {
      const r = await ragRetryTask(docId)
      setHint(r.message || `已重新排队「${name}」`)
      setPollTaskId(docId)
      setUploading(true)
      setUploadStatus('queued')
      setUploadPct(0)
      await refreshAll()
    } catch (e) {
      setErr(formatApiError(e, 'chat:write'))
    } finally {
      setBusy(false)
    }
  }

  const onDelete = async (source: string, name: string) => {
    if (!source) {
      setErr('该条目缺少 source，无法单独删除（可联系管理员重置知识库）')
      return
    }
    if (!window.confirm(`确定删除「${name}」及其全部向量块？`)) return
    setBusy(true)
    setErr('')
    try {
      const r = await ragDeleteDocument(source)
      setHint(r.message || '已删除')
      await refreshAll()
    } catch (e) {
      setErr(formatApiError(e, 'chat:write'))
    } finally {
      setBusy(false)
    }
  }

  const onAsk = async () => {
    setBusy(true)
    setErr('')
    try {
      const r = await ragAsk(q)
      setAsk(r.data)
      await loadStatus()
    } catch (e) {
      setErr(formatApiError(e, 'chat:write'))
    } finally {
      setBusy(false)
    }
  }

  const onSearch = async () => {
    setBusy(true)
    setErr('')
    try {
      const r = await ragSearch(q)
      setSearch(r.data)
    } catch (e) {
      setErr(formatApiError(e, 'chat:write'))
    } finally {
      setBusy(false)
    }
  }

  const ratio = stats?.cache?.hit_ratio
  const hitPct =
    typeof ratio === 'number' ? `${(ratio * 100).toFixed(1)}%` : '—'
  const chunkTotal = stats?.document_count ?? 0

  return (
    <div className="mx-auto w-full max-w-5xl flex-1 overflow-auto px-6 py-6">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A]">知识库</h1>
          <p className="mt-1 text-sm text-[#64748B]">
            上传公司 PDF 资料，检索与对话会引用这些内容（与主讲风格上传无关）。
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          disabled={busy}
          onClick={() => void refreshAll()}
        >
          刷新
        </Button>
      </div>

      <ForbiddenBanner />

      {err ? (
        <p
          className="mb-4 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
          role="alert"
        >
          {err}
        </p>
      ) : null}
      {hint ? (
        <p
          className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800"
          role="status"
        >
          {hint}
        </p>
      ) : null}

      {/* 概览 */}
      <section className="mb-6 grid gap-3 sm:grid-cols-3">
        <div className="rounded-2xl border border-[#E2E8F0] bg-white px-4 py-4 shadow-sm">
          <div className="text-xs font-medium tracking-wide text-[#64748B] uppercase">
            文档数
          </div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-[#0F172A]">
            {docs.length}
          </div>
        </div>
        <div className="rounded-2xl border border-[#E2E8F0] bg-white px-4 py-4 shadow-sm">
          <div className="text-xs font-medium tracking-wide text-[#64748B] uppercase">
            向量块
          </div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-[#0F172A]">
            {chunkTotal}
          </div>
        </div>
        <div className="rounded-2xl border border-[#E2E8F0] bg-white px-4 py-4 shadow-sm">
          <div className="text-xs font-medium tracking-wide text-[#64748B] uppercase">
            缓存命中率
          </div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-2xl font-semibold tabular-nums text-[#0F172A]">
              {hitPct}
            </span>
            <span className="text-xs text-[#94A3B8]">
              {stats?.cache?.enabled ? 'on' : 'off'} · hit=
              {stats?.cache?.hit ?? 0}
            </span>
          </div>
        </div>
      </section>

      {/* 上传 */}
      <section className="mb-6 overflow-hidden rounded-2xl border border-[#E2E8F0] bg-white shadow-sm">
        <div className="border-b border-[#E2E8F0] px-5 py-4">
          <h2 className="text-sm font-semibold text-[#0F172A]">上传 PDF</h2>
          <p className="mt-0.5 text-xs text-[#64748B]">
            须真实 PDF（带文本层）。上传后立即排队，可离开页面；扫描件请先 OCR 或走图片分支。
          </p>
        </div>
        <div className="space-y-4 px-5 py-5">
          <div className="space-y-1.5">
            <Label htmlFor="rag-pdf" className="text-sm font-medium text-[#334155]">
              选择文件
            </Label>
            <Input
              ref={fileInputRef}
              id="rag-pdf"
              type="file"
              accept=".pdf,application/pdf"
              disabled={busy}
              className="h-11 max-w-xl rounded-xl border-[#E2E8F0] bg-[#F8FAFC]"
              onChange={onFileChange}
            />
            {pdfFile ? (
              <p className="text-xs text-[#64748B]">
                已选：{pdfFile.name}（{(pdfFile.size / 1024).toFixed(1)} KB）
              </p>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              disabled={busy || !pdfFile}
              className="h-10 rounded-xl bg-[#165DFF] px-5 font-semibold text-white hover:bg-[#1263D8]"
              onClick={() => void onUpload()}
            >
              {uploading ? '已排队…' : '上传到知识库'}
            </Button>
          </div>
          {uploading ? (
            <div className="max-w-xl">
              <Progress
                value={uploadPct}
                label={uploadPhaseLabel(uploadStatus, uploadPct)}
              />
            </div>
          ) : null}
        </div>
      </section>

      {/* 文档管理 */}
      <section className="mb-6 overflow-hidden rounded-2xl border border-[#E2E8F0] bg-white shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#E2E8F0] px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold text-[#0F172A]">已入库文档</h2>
            <p className="mt-0.5 text-xs text-[#64748B]">
              按文件名聚合；删除会清除该文件对应的全部向量块。失败可重试。
            </p>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-[#F8FAFC] text-xs tracking-wide text-[#64748B] uppercase">
              <tr>
                <th className="px-5 py-3 font-semibold">文件名</th>
                <th className="px-5 py-3 font-semibold">类型</th>
                <th className="px-5 py-3 font-semibold">状态</th>
                <th className="px-5 py-3 font-semibold">向量块</th>
                <th className="px-5 py-3 font-semibold">最近入库</th>
                <th className="px-5 py-3 font-semibold">操作</th>
              </tr>
            </thead>
            <tbody>
              {docs.length === 0 ? (
                <tr>
                  <td
                    colSpan={6}
                    className="px-5 py-12 text-center text-[#64748B]"
                  >
                    暂无文档 — 在上方上传 PDF 后会出现在这里
                  </td>
                </tr>
              ) : (
                docs.map((d) => (
                  <tr
                    key={d.doc_id || `${d.source}-${d.source_type}`}
                    className="border-t border-[#E2E8F0]"
                  >
                    <td
                      className="max-w-xs truncate px-5 py-3 font-medium text-[#0F172A]"
                      title={d.name}
                    >
                      {d.name}
                    </td>
                    <td className="px-5 py-3 text-[#64748B]">
                      <Badge variant="outline" className="font-normal">
                        {d.source_type || 'text'}
                      </Badge>
                    </td>
                    <td className="px-5 py-3">
                      <div className="flex flex-col gap-0.5">
                        <Badge
                          variant={statusBadgeVariant(d.status)}
                          className="font-normal"
                        >
                          {statusLabel(d.status)}
                        </Badge>
                        {d.status === 'failed' && d.error_code ? (
                          <span className="text-[11px] text-red-600">
                            {d.error_code}
                          </span>
                        ) : null}
                      </div>
                    </td>
                    <td className="px-5 py-3 tabular-nums text-[#334155]">
                      {d.chunk_count}
                    </td>
                    <td className="px-5 py-3 whitespace-nowrap text-[#64748B]">
                      {d.created_at
                        ? d.created_at.replace('T', ' ').slice(0, 19)
                        : '—'}
                    </td>
                    <td className="px-5 py-3">
                      <div className="flex flex-wrap gap-2">
                        {d.status === 'failed' && d.doc_id ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            disabled={busy}
                            className="h-8 rounded-lg text-xs"
                            onClick={() => void onRetry(d.doc_id as string, d.name)}
                          >
                            重试
                          </Button>
                        ) : null}
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={busy || !d.source}
                          className={cn(
                            'h-8 rounded-lg text-xs',
                            !d.source && 'opacity-50',
                          )}
                          onClick={() => void onDelete(d.source, d.name)}
                        >
                          删除
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* 提问 / 搜索 */}
      <section className="overflow-hidden rounded-2xl border border-[#E2E8F0] bg-white shadow-sm">
        <div className="border-b border-[#E2E8F0] px-5 py-4">
          <h2 className="text-sm font-semibold text-[#0F172A]">提问 / 搜索</h2>
          <p className="mt-0.5 text-xs text-[#64748B]">
            同问两次可观察缓存命中；Search 只返回检索片段。
          </p>
        </div>
        <div className="space-y-4 px-5 py-5">
          <div className="space-y-1.5">
            <Label htmlFor="rag-q" className="text-sm font-medium text-[#334155]">
              问题
            </Label>
            <Input
              id="rag-q"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className="h-11 max-w-2xl rounded-xl border-[#E2E8F0] bg-[#F8FAFC]"
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              disabled={busy}
              className="h-10 rounded-xl bg-[#165DFF] px-5 font-semibold text-white hover:bg-[#1263D8]"
              onClick={() => void onAsk()}
            >
              Ask
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              className="h-10 rounded-xl"
              onClick={() => void onSearch()}
            >
              Search
            </Button>
          </div>
          {ask ? (
            <div className="space-y-2 rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] p-4">
              <div className="flex flex-wrap items-center gap-2">
                {ask.cache_hit ? (
                  <Badge variant="success">cache_hit · 零成本</Badge>
                ) : (
                  <Badge variant="outline">cache_miss</Badge>
                )}
                <span className="text-xs tabular-nums text-[#94A3B8]">
                  {ask.latency_ms != null ? `${ask.latency_ms.toFixed(0)}ms` : ''}
                </span>
              </div>
              <p className="text-sm whitespace-pre-wrap text-[#0F172A]">
                {ask.answer || '（无回答）'}
              </p>
            </div>
          ) : null}
          {search ? (
            <pre className="overflow-auto rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] p-3 text-xs text-[#334155]">
              {JSON.stringify(search, null, 2)}
            </pre>
          ) : null}
        </div>
      </section>
    </div>
  )
}
