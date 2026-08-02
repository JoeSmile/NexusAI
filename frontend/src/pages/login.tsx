import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { RoleSwitcher } from '@/components/role/RoleSwitcher'
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
import { ROLE_BADGE, ROLE_SHORT } from '@/components/role/roleStyles'
import { useAuthStore } from '@/stores/authStore'
import { cn } from '@/lib/utils'

export default function LoginPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const loginWithKey = useAuthStore((s) => s.loginWithKey)
  const keys = useAuthStore((s) => s.keys)
  const activeRole = useAuthStore((s) => s.activeRole)

  const [keyInput, setKeyInput] = useState(keys[activeRole] || '')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const role = activeRole

  useEffect(() => {
    setKeyInput(keys[role] || '')
  }, [role, keys])

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
            测试 FE 登录 — 选择角色槽位，填入 API Key，经 /health 探活
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={onSubmit}>
            <div className="flex items-center justify-between gap-2">
              <Badge className={cn('rounded-full', ROLE_BADGE[role])}>
                {ROLE_SHORT[role]}
              </Badge>
              <RoleSwitcher />
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
