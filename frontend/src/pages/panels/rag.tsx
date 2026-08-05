import { useEffect, useRef, useState, type ChangeEvent } from 'react'

import { formatApiError } from '@/api/http'
import {
  ragAsk,
  ragSearch,
  ragStatus,
  ragUploadPdf,
  type RagAskData,
  type RagStatusData,
} from '@/api/rag'
import { ForbiddenBanner } from '@/components/role/RoleSwitcher'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { useAuthStore } from '@/stores/authStore'

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
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadPct, setUploadPct] = useState(0)
  const [err, setErr] = useState('')
  const [pdfFile, setPdfFile] = useState<File | null>(null)
  const [uploadMsg, setUploadMsg] = useState('')
  const [uploadedNames, setUploadedNames] = useState<string[]>([])
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
        // 后端无真实进度流:缓升到 90%,等请求结束后再拉满
        if (p >= 90) return 90
        if (p >= 55) return p + 1.5
        if (p >= 25) return p + 2.5
        return p + 4
      })
    }, 400)
  }

  useEffect(() => () => stopProgressTicker(), [])

  const loadStatus = async () => {
    try {
      const r = await ragStatus()
      setStats(r.data)
    } catch (e) {
      setErr(formatApiError(e, 'chat:write'))
    }
  }

  useEffect(() => {
    void loadStatus()
  }, [])

  useEffect(() => {
    if (skip.current) {
      skip.current = false
      return
    }
    setAsk(null)
    setSearch(null)
    setUploadMsg('')
    setUploading(false)
    setUploadPct(0)
    setUploadedNames([])
    stopProgressTicker()
    void loadStatus()
  }, [roleEpoch])

  const onFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null
    setUploadMsg('')
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
    setUploadMsg('')
    startProgressTicker()
    const name = pdfFile.name
    try {
      const r = await ragUploadPdf(pdfFile)
      stopProgressTicker()
      setUploadPct(100)
      setUploadMsg(r.message || '上传成功')
      setUploadedNames((prev) =>
        prev.includes(name) ? prev : [...prev, name],
      )
      setPdfFile(null)
      if (fileInputRef.current) fileInputRef.current.value = ''
      await loadStatus()
      window.setTimeout(() => {
        setUploading(false)
        setUploadPct(0)
      }, 800)
    } catch (e) {
      stopProgressTicker()
      setUploading(false)
      setUploadPct(0)
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

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">RAG</h1>
        <p className="text-muted-foreground text-xs">
          /api/rag/ask · search · status · upload/pdf — 同问两次看 cache_hit
        </p>
      </div>
      <ForbiddenBanner />

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle className="text-sm font-semibold">缓存状态</CardTitle>
            <CardDescription className="text-muted-foreground text-xs">
              GET /api/rag/status
            </CardDescription>
          </div>
          <StatusBadge
            status={stats?.cache?.enabled ? 'success' : 'idle'}
            label={stats?.cache?.enabled ? 'cache on' : 'cache off'}
          />
        </CardHeader>
        <CardContent className="text-xs space-y-1">
          <p>
            命中率 <strong className="tabular-nums">{hitPct}</strong>
            （hit={stats?.cache?.hit ?? 0} / miss={stats?.cache?.miss ?? 0}）
          </p>
          <p className="text-muted-foreground">
            docs={stats?.document_count ?? '—'} · {stats?.status || '—'}
          </p>
          <Button type="button" size="sm" variant="outline" onClick={() => void loadStatus()}>
            刷新 status
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">上传 PDF</CardTitle>
          <CardDescription className="text-muted-foreground text-xs">
            POST /api/rag/upload/pdf — 须真实 PDF（.md 改后缀会被 pypdf 解析失败）
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
            <div className="min-w-0 flex-1 space-y-3">
              <div className="space-y-1">
                <Label htmlFor="rag-pdf">PDF 文件</Label>
                <Input
                  ref={fileInputRef}
                  id="rag-pdf"
                  type="file"
                  accept=".pdf,application/pdf"
                  disabled={uploading}
                  onChange={onFileChange}
                />
              </div>
              {pdfFile ? (
                <p className="text-muted-foreground text-xs">
                  已选：{pdfFile.name}（{(pdfFile.size / 1024).toFixed(1)} KB）
                </p>
              ) : null}
              <Button
                type="button"
                disabled={busy || uploading || !pdfFile}
                onClick={() => void onUpload()}
              >
                {uploading ? '处理中…' : '上传到知识库'}
              </Button>
              {uploading ? (
                <Progress value={uploadPct} label={uploadPhaseLabel(uploadPct)} />
              ) : null}
              {uploadMsg ? (
                <p
                  className="text-xs text-green-700 dark:text-green-400"
                  role="status"
                >
                  {uploadMsg}
                </p>
              ) : null}
            </div>

            <div className="sm:w-56 sm:shrink-0 sm:border-l sm:border-border sm:pl-4">
              <p className="mb-2 text-xs font-medium">已上传</p>
              {uploadedNames.length === 0 ? (
                <p className="text-muted-foreground text-xs">本会话暂无上传</p>
              ) : (
                <ul className="space-y-1.5">
                  {uploadedNames.map((n) => (
                    <li
                      key={n}
                      className="truncate rounded-md border border-border px-2 py-1 text-xs"
                      title={n}
                    >
                      {n}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">提问 / 搜索</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1">
            <Label htmlFor="rag-q">问题</Label>
            <Input id="rag-q" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <div className="flex gap-2">
            <Button type="button" disabled={busy} onClick={() => void onAsk()}>
              Ask
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => void onSearch()}
            >
              Search
            </Button>
          </div>
          {err ? (
            <p className="text-destructive text-sm" role="alert">
              {err}
            </p>
          ) : null}
          {ask ? (
            <div className="space-y-2 rounded-lg border border-border p-3">
              <div className="flex items-center gap-2">
                {ask.cache_hit ? (
                  <Badge variant="success">cache_hit · 零成本</Badge>
                ) : (
                  <Badge variant="outline">cache_miss</Badge>
                )}
                <span className="text-muted-foreground text-xs tabular-nums">
                  {ask.latency_ms != null ? `${ask.latency_ms.toFixed(0)}ms` : ''}
                </span>
              </div>
              <p className="text-sm whitespace-pre-wrap">{ask.answer || '（无回答）'}</p>
            </div>
          ) : null}
          {search ? (
            <pre className="overflow-auto rounded-lg border border-border p-2 text-xs">
              {JSON.stringify(search, null, 2)}
            </pre>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}
