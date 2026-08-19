/**
 * 知识库 RAG — 工作区页（上传 / 文档管理 / 检索）
 */
import { useCallback, useEffect, useRef, useState, type ChangeEvent } from 'react'

import { formatApiError } from '@/api/http'
import {
  ragAsk,
  ragDeleteDocument,
  ragListDocuments,
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

function uploadPhaseLabel(pct: number): string {
  if (pct >= 100) return '入库完成'
  if (pct >= 55) return 'Embedding 向量化中…'
  if (pct >= 25) return '解析 PDF…'
  return '上传文件中…'
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
  const [err, setErr] = useState('')
  const [hint, setHint] = useState('')
  const [pdfFile, setPdfFile] = useState<File | null>(null)
  const skip = useRef(true)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const progressTimer = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopProgressTicker = () => {
    if (progressTimer.current) {
      clearInterval(progressTimer.current)
      progressTimer.current = null
    }
  }

  const startProgressTicker = () => {
    stopProgressTicker()
    setUploadPct(5)
    progressTimer.current = setInterval(() => {
      setUploadPct((p) => {
        if (p >= 90) return 90
        if (p >= 55) return p + 1.5
        if (p >= 25) return p + 2.5
        return p + 4
      })
    }, 400)
  }

  useEffect(() => () => stopProgressTicker(), [])

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
    setHint('')
    setErr('')
    stopProgressTicker()
    void refreshAll()
  }, [roleEpoch, refreshAll])

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
    setErr('')
    setHint('')
    startProgressTicker()
    try {
      const r = await ragUploadPdf(pdfFile)
      stopProgressTicker()
      setUploadPct(100)
      setHint(r.message || '上传成功')
      setPdfFile(null)
      if (fileInputRef.current) fileInputRef.current.value = ''
      await refreshAll()
      window.setTimeout(() => {
        setUploading(false)
        setUploadPct(0)
      }, 600)
    } catch (e) {
      stopProgressTicker()
      setUploading(false)
      setUploadPct(0)
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
            须真实 PDF（带文本层）。扫描件请先 OCR 或走图片分支。
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
              disabled={uploading}
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
              disabled={busy || uploading || !pdfFile}
              className="h-10 rounded-xl bg-[#165DFF] px-5 font-semibold text-white hover:bg-[#1263D8]"
              onClick={() => void onUpload()}
            >
              {uploading ? '处理中…' : '上传到知识库'}
            </Button>
          </div>
          {uploading ? (
            <div className="max-w-xl">
              <Progress value={uploadPct} label={uploadPhaseLabel(uploadPct)} />
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
              按文件名聚合；删除会清除该文件对应的全部向量块。
            </p>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-[#F8FAFC] text-xs tracking-wide text-[#64748B] uppercase">
              <tr>
                <th className="px-5 py-3 font-semibold">文件名</th>
                <th className="px-5 py-3 font-semibold">类型</th>
                <th className="px-5 py-3 font-semibold">向量块</th>
                <th className="px-5 py-3 font-semibold">最近入库</th>
                <th className="px-5 py-3 font-semibold">操作</th>
              </tr>
            </thead>
            <tbody>
              {docs.length === 0 ? (
                <tr>
                  <td
                    colSpan={5}
                    className="px-5 py-12 text-center text-[#64748B]"
                  >
                    暂无文档 — 在上方上传 PDF 后会出现在这里
                  </td>
                </tr>
              ) : (
                docs.map((d) => (
                  <tr
                    key={`${d.source}-${d.source_type}`}
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
                    <td className="px-5 py-3 tabular-nums text-[#334155]">
                      {d.chunk_count}
                    </td>
                    <td className="px-5 py-3 whitespace-nowrap text-[#64748B]">
                      {d.created_at
                        ? d.created_at.replace('T', ' ').slice(0, 19)
                        : '—'}
                    </td>
                    <td className="px-5 py-3">
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
