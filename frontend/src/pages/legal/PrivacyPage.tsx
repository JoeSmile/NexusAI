import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'

import { fetchTermsCurrent, type TermsDoc } from '@/api/terms'
import { formatApiError } from '@/api/http'
import { Link } from 'react-router-dom'

export default function PrivacyPage() {
  const [doc, setDoc] = useState<TermsDoc | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    void (async () => {
      try {
        setDoc(await fetchTermsCurrent('privacy'))
      } catch (e) {
        setErr(formatApiError(e))
      }
    })()
  }, [])

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <Link to="/terms?kind=privacy" className="text-sm text-slate-500">
        ← 条款中心
      </Link>
      <h1 className="text-2xl font-semibold">隐私政策</h1>
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
