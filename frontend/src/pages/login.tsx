import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ROLE_BADGE, ROLE_SHORT } from '@/components/role/roleStyles'
import { ApiError } from '@/api/http'
import { useAuthStore } from '@/stores/authStore'
import { cn } from '@/lib/utils'

function passwordErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 401) return '用户名或密码错误'
    if (e.status === 429) return '尝试过多，请稍后再试'
    return `[${e.code}] ${e.message}`
  }
  if (e instanceof Error) return e.message
  return 'login_failed'
}

export default function LoginPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const loginWithKey = useAuthStore((s) => s.loginWithKey)
  const loginWithPassword = useAuthStore((s) => s.loginWithPassword)
  const keys = useAuthStore((s) => s.keys)
  const activeRole = useAuthStore((s) => s.activeRole)

  const [keyInput, setKeyInput] = useState(keys[activeRole] || '')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const role = activeRole

  // 密码 tab 状态
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [pwError, setPwError] = useState('')
  const [pwBusy, setPwBusy] = useState(false)

  useEffect(() => {
    setKeyInput(keys[role] || '')
  }, [role, keys])

  const onSubmitKey = async (e: FormEvent) => {
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

  const onSubmitPassword = async (e: FormEvent) => {
    e.preventDefault()
    setPwError('')
    setPwBusy(true)
    try {
      await loginWithPassword(username, password)
      const next = params.get('next') || '/panels/chat'
      navigate(next.startsWith('/') ? next : '/panels/chat', { replace: true })
    } catch (err) {
      setPwError(passwordErrorMessage(err))
    } finally {
      setPwBusy(false)
    }
  }

  return (
    <div className="flex min-h-svh items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md shadow-[var(--shadow-overlay)]">
        <CardHeader>
          <CardTitle className="text-xl font-semibold">ContextGate</CardTitle>
          <CardDescription className="text-muted-foreground text-xs">
            测试 FE 登录 — 密码登录 / Key 登录
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="password" className="w-full">
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="password">密码登录</TabsTrigger>
              <TabsTrigger value="key">Key 登录</TabsTrigger>
            </TabsList>

            <TabsContent value="password">
              <form className="space-y-4" onSubmit={onSubmitPassword}>
                <div className="space-y-1.5">
                  <Label htmlFor="login-username">用户名</Label>
                  <Input
                    id="login-username"
                    type="text"
                    autoComplete="username"
                    placeholder="alice"
                    value={username}
                    onChange={(ev) => setUsername(ev.target.value)}
                    required
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="login-password">密码</Label>
                  <Input
                    id="login-password"
                    type="password"
                    autoComplete="current-password"
                    placeholder="••••••••"
                    value={password}
                    onChange={(ev) => setPassword(ev.target.value)}
                    required
                  />
                </div>
                {pwError ? (
                  <p className="text-destructive text-xs" role="alert">
                    {pwError}
                  </p>
                ) : null}
                <Button type="submit" className="w-full" disabled={pwBusy}>
                  {pwBusy ? '登录中…' : '登录'}
                </Button>
                <div className="text-muted-foreground text-xs text-center">
                  没有账号？
                  <Link
                    to="/register"
                    className="text-primary ml-1 underline-offset-2 hover:underline"
                  >
                    前往注册
                  </Link>
                </div>
              </form>
            </TabsContent>

            <TabsContent value="key">
              <form className="space-y-4" onSubmit={onSubmitKey}>
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
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  )
}
