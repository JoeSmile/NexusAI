import { useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

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
import { ROLES, useAuthStore } from '@/stores/authStore'
import type { RoleName } from '@/types/api'

const ROLE_LABEL: Record<RoleName, string> = {
  user: 'user',
  tenant_admin: 'tenant_admin',
  auditor: 'auditor',
  super_admin: 'super_admin',
}

export default function LoginPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const loginWithKey = useAuthStore((s) => s.loginWithKey)
  const keys = useAuthStore((s) => s.keys)
  const activeRole = useAuthStore((s) => s.activeRole)
  const switchRole = useAuthStore((s) => s.switchRole)

  const [role, setRole] = useState<RoleName>(activeRole)
  const [keyInput, setKeyInput] = useState(keys[activeRole] || '')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      await loginWithKey(role, keyInput)
      const next = params.get('next') || '/panels/chat'
      navigate(next.startsWith('/') ? next : '/panels/chat', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'login_failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-svh items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md shadow-[var(--shadow-overlay)]">
        <CardHeader>
          <CardTitle className="text-xl font-semibold">ContextGate</CardTitle>
          <CardDescription className="text-muted-foreground text-xs">
            测试 FE 登录 — 填入 API Key，经 /health 探活后写入角色槽位
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={onSubmit}>
            <div className="flex flex-wrap gap-1.5">
              {ROLES.map((r) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => {
                    setRole(r)
                    switchRole(r)
                    setKeyInput(keys[r] || '')
                  }}
                  className="focus-visible:outline-none"
                >
                  <Badge variant={role === r ? 'default' : 'outline'}>
                    {ROLE_LABEL[r]}
                  </Badge>
                </button>
              ))}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="api-key">X-API-Key（{role}）</Label>
              <Input
                id="api-key"
                type="password"
                autoComplete="off"
                placeholder="cg_..."
                value={keyInput}
                onChange={(ev) => setKeyInput(ev.target.value)}
              />
            </div>
            {error ? (
              <p className="text-destructive text-xs" role="alert">
                {error}
              </p>
            ) : null}
            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? '验证中…' : '进入控制台'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
