import { useState, type FormEvent, type ReactNode } from 'react'

import { apiFetch, ApiError } from '@/api/http'
import { ForbiddenBanner } from '@/components/role/RoleSwitcher'
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
import { ROLE_BADGE, ROLE_SHORT } from '@/components/role/roleStyles'
import { Badge } from '@/components/ui/badge'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { useAuthStore } from '@/stores/authStore'
import { useForbiddenStore } from '@/stores/forbiddenStore'
import type { RoleName } from '@/types/api'
import { cn } from '@/lib/utils'

export type FieldDef = {
  name: string
  label: string
  type?: 'text' | 'password' | 'number'
  placeholder?: string
  defaultValue?: string
}

type Props = {
  title: string
  description?: string
  fields: FieldDef[]
  endpoint: string
  method?: string
  onSend?: (values: Record<string, string>) => Promise<unknown>
  renderResult?: (data: unknown) => ReactNode
}

export function RequestPanel({
  title,
  description,
  fields,
  endpoint,
  method = 'GET',
  onSend,
  renderResult,
}: Props) {
  const role = useAuthStore((s) => s.activeRole) as RoleName
  const clearForbidden = useForbiddenStore((s) => s.clear)
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map((f) => [f.name, f.defaultValue || ''])),
  )
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<number | null>(null)
  const [ms, setMs] = useState<number | null>(null)
  const [result, setResult] = useState<unknown>(null)
  const [localErr, setLocalErr] = useState('')

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    clearForbidden()
    setLocalErr('')
    setBusy(true)
    setResult(null)
    setStatus(null)
    const t0 = performance.now()
    try {
      let data: unknown
      let code = 200
      if (onSend) {
        data = await onSend(values)
      } else {
        const res = await apiFetch(endpoint, {
          method,
          body:
            method === 'GET' || method === 'HEAD'
              ? undefined
              : JSON.stringify(values),
        })
        code = res.status
        data = await res.json().catch(() => null)
      }
      setStatus(code)
      setResult(data)
    } catch (err) {
      if (err instanceof ApiError) {
        setStatus(err.status)
        if (!err.forbidden) setLocalErr(`[${err.code}] ${err.message}`)
      } else {
        setLocalErr(err instanceof Error ? err.message : String(err))
      }
    } finally {
      setMs(Math.round(performance.now() - t0))
      setBusy(false)
    }
  }

  const kind =
    status == null
      ? busy
        ? 'pending'
        : 'idle'
      : status >= 200 && status < 300
        ? 'success'
        : status === 403
          ? 'error'
          : status >= 400
            ? 'error'
            : 'warning'

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <div>
          <CardTitle className="text-sm font-semibold">{title}</CardTitle>
          {description ? (
            <CardDescription className="text-muted-foreground text-xs">
              {description}
            </CardDescription>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={kind as 'idle' | 'pending' | 'success' | 'error' | 'warning'} />
          <Badge className={cn('rounded-full', ROLE_BADGE[role])}>
            {ROLE_SHORT[role]}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <ForbiddenBanner />
        <form className="space-y-3" onSubmit={submit}>
          {fields.map((f) => (
            <div key={f.name} className="space-y-1">
              <Label htmlFor={`${title}-${f.name}`}>{f.label}</Label>
              <Input
                id={`${title}-${f.name}`}
                type={f.type || 'text'}
                placeholder={f.placeholder}
                value={values[f.name] || ''}
                onChange={(ev) =>
                  setValues((v) => ({ ...v, [f.name]: ev.target.value }))
                }
              />
            </div>
          ))}
          <div className="flex items-center gap-2">
            <Button type="submit" disabled={busy}>
              {busy ? '发送中…' : '发送'}
            </Button>
            <span className="text-muted-foreground text-xs">
              {method} {endpoint}
              {status != null ? ` · HTTP ${status}` : ''}
              {ms != null ? ` · ${ms}ms` : ''}
            </span>
          </div>
        </form>
        {localErr ? (
          <p className="text-destructive text-sm" role="alert">
            {localErr}
          </p>
        ) : null}
        <div className="min-h-24 rounded-lg border border-border bg-background p-2">
          {result == null && !busy && !localErr ? (
            <p className="text-muted-foreground text-xs">空态 — 发送请求查看响应</p>
          ) : null}
          {busy ? (
            <p className="text-muted-foreground text-xs">加载中…</p>
          ) : null}
          {result != null
            ? renderResult
              ? renderResult(result)
              : (
                  <pre className="overflow-auto text-xs">
                    {typeof result === 'string'
                      ? result
                      : JSON.stringify(result, null, 2)}
                  </pre>
                )
            : null}
        </div>
      </CardContent>
    </Card>
  )
}
