/**
 * AgentUI-styled login — password primary.
 */
import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { ApiError } from '@/api/http'
import { acceptTerms, fetchTermsCurrent, USER_AGREEMENT_KIND, type TermsDoc } from '@/api/terms'
import { resolvePostLoginPath } from '@/lib/routes'
import { useAuthStore } from '@/stores/authStore'

function passwordErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 401) return '用户名或密码错误'
    if (e.status === 429) return '尝试过多，请稍后再试'
    return `[${e.code}] ${e.message}`
  }
  if (e instanceof Error) return e.message
  return 'login_failed'
}

export default function AgentLoginPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const loginWithPassword = useAuthStore((s) => s.loginWithPassword)
  const [username, setUsername] = useState('content_demo')
  const [password, setPassword] = useState('')
  const [agreed, setAgreed] = useState(false)
  const [termsDoc, setTermsDoc] = useState<TermsDoc | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const doc = await fetchTermsCurrent(USER_AGREEMENT_KIND)
        if (!cancelled) setTermsDoc(doc)
      } catch {
        if (!cancelled) setTermsDoc(null)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!agreed) {
      setError('请先阅读并同意用户协议')
      return
    }
    setError('')
    setBusy(true)
    try {
      await loginWithPassword(username, password)
      if (termsDoc) {
        await acceptTerms(termsDoc.kind, termsDoc.version)
      }
      navigate(resolvePostLoginPath(params.get('next')), { replace: true })
    } catch (err) {
      setError(passwordErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="relative flex min-h-svh items-center justify-center overflow-hidden"
      style={{
        fontFamily: "Inter, 'Noto Sans SC', system-ui, sans-serif",
        background:
          'radial-gradient(ellipse at top left, #EEF2FF 0%, #F8FAFC 45%, #F1F5F9 100%)',
      }}
    >
      <div className="absolute inset-0 opacity-40" style={{
        backgroundImage:
          'radial-gradient(circle at 80% 20%, #C7D2FE 0%, transparent 40%)',
      }} />
      <form
        onSubmit={onSubmit}
        className="relative w-full max-w-[400px] rounded-2xl border border-slate-200/80 bg-white p-8 shadow-xl"
      >
        <div className="mb-6 flex flex-col items-center gap-2 text-center">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-indigo-600 text-lg font-bold text-white">
            N
          </div>
          <h1 className="text-xl font-semibold text-slate-900">NexusAI</h1>
          <p className="text-xs text-slate-500">内容运营 · 智能工作台</p>
        </div>
        <label htmlFor="login-username" className="mb-1 block text-xs font-medium text-slate-600">
          用户名
        </label>
        <input
          id="login-username"
          className="mb-3 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          required
        />
        <label htmlFor="login-password" className="mb-1 block text-xs font-medium text-slate-600">
          密码
        </label>
        <input
          id="login-password"
          type="password"
          className="mb-4 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          required
        />
        <label className="mb-4 flex cursor-pointer items-start gap-2 text-xs leading-5 text-slate-600">
          <input
            type="checkbox"
            className="mt-0.5 h-3.5 w-3.5 shrink-0 rounded border-slate-300 text-indigo-600"
            checked={agreed}
            onChange={(e) => setAgreed(e.target.checked)}
          />
          <span>
            我已阅读并同意
            <Link
              to="/terms"
              target="_blank"
              rel="noreferrer"
              className="mx-0.5 font-medium text-indigo-600 underline-offset-2 hover:underline"
              onClick={(ev) => ev.stopPropagation()}
            >
              《用户协议》
            </Link>
          </span>
        </label>
        {error ? (
          <p className="mb-3 text-xs text-rose-600" role="alert">
            {error}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={busy || !agreed}
          className="w-full rounded-lg bg-indigo-600 py-2.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-60"
        >
          {busy ? '登录中…' : '登录'}
        </button>
        <p className="mt-4 text-center text-xs text-slate-500">
          账号由管理员开通，请使用已发放的账号登录
        </p>
      </form>
    </div>
  )
}
