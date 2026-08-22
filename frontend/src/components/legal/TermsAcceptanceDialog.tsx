import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { Link } from 'react-router-dom'

import { acceptTerms, type TermsDoc } from '@/api/terms'
import { formatApiError } from '@/api/http'
import { Button } from '@/components/ui/button'

type Props = {
  pending: TermsDoc[]
  onAccepted: () => void
}

export function TermsAcceptanceDialog({ pending, onAccepted }: Props) {
  const [idx, setIdx] = useState(0)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  if (!pending.length) return null

  const doc = pending[idx] ?? pending[0]

  const onAccept = async () => {
    setBusy(true)
    setErr('')
    try {
      await acceptTerms(doc.kind, doc.version)
      if (idx + 1 < pending.length) {
        setIdx(idx + 1)
      } else {
        onAccepted()
      }
    } catch (e) {
      setErr(formatApiError(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="terms-dialog-title"
    >
      <div className="max-h-[85vh] w-full max-w-lg overflow-auto rounded-lg bg-white p-6 shadow-lg">
        <h2 id="terms-dialog-title" className="text-lg font-semibold">
          请阅读并同意（{idx + 1}/{pending.length}）
        </h2>
        <p className="text-sm text-muted-foreground">
          {doc.kind} · 版本 {doc.version}
        </p>
        <article className="prose prose-sm mt-4 max-h-64 overflow-auto">
          <ReactMarkdown>{doc.content_md}</ReactMarkdown>
        </article>
        <p className="mt-3 text-xs text-muted-foreground">
          完整文本见{' '}
          <Link to={`/terms?kind=${doc.kind}`} className="underline" target="_blank">
            条款页
          </Link>
        </p>
        {err ? <p className="mt-2 text-sm text-red-600">{err}</p> : null}
        <div className="mt-4 flex justify-end gap-2">
          <Button type="button" disabled={busy} onClick={() => void onAccept()}>
            同意并继续
          </Button>
        </div>
      </div>
    </div>
  )
}
