import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'

import { fetchTermsCurrent, USER_AGREEMENT_KIND, type TermsDoc } from '@/api/terms'
import { formatApiError } from '@/api/http'

const KIND_LABELS: Record<string, string> = {
  [USER_AGREEMENT_KIND]: '用户协议',
  privacy: '隐私政策（归档）',
  general: '平台通用条款（归档）',
  company_key: '公司 Key 服务条款（归档）',
  byok: 'BYOK 服务条款（归档）',
}

export default function TermsPage() {
  const [params] = useSearchParams()
  const kind = params.get('kind') || USER_AGREEMENT_KIND
  const [doc, setDoc] = useState<TermsDoc | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    void (async () => {
      setErr('')
      try {
        setDoc(await fetchTermsCurrent(kind))
      } catch (e) {
        setDoc(null)
        setErr(formatApiError(e))
      }
    })()
  }, [kind])

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <div className="flex flex-wrap gap-3 text-sm">
        <Link
          to="/terms"
          className={kind === USER_AGREEMENT_KIND ? 'font-semibold text-slate-900' : 'text-slate-500'}
        >
          用户协议
        </Link>
        <Link to="/login" className="text-slate-500">
          返回登录
        </Link>
      </div>
      <h1 className="text-2xl font-semibold">{KIND_LABELS[kind] || '条款'}</h1>
      {doc ? (
        <p className="text-sm text-muted-foreground">版本 {doc.version}</p>
      ) : null}
      {err ? <p className="text-sm text-red-600">{err}</p> : null}
      <article className="prose prose-sm max-w-none dark:prose-invert">
        {doc ? <ReactMarkdown>{doc.content_md}</ReactMarkdown> : null}
      </article>
    </div>
  )
}
