import { useMemo, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { BrandMark } from '@/components/brand/BrandMark'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ApiError } from '@/api/http'
import { registerAccount } from '@/api/auth'
import { HOME_PATH } from '@/lib/routes'
import { ROLES, useAuthStore } from '@/stores/authStore'
import type { RoleName } from '@/types/api'

const MIN_PASSWORD_LEN = 8

function registerErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === 'AUTH_014') return '用户名已被占用'
    if (e.code === 'AUTH_010') return '注册已关闭（生产环境不可注册）'
    if (e.code === 'AUTH_011') return '请输入用户名'
    if (e.code === 'AUTH_012') return '密码至少 8 位'
    if (e.code === 'AUTH_013') return '角色无效'
    if (e.status === 429) return '尝试过多，请稍后再试'
    return `[${e.code}] ${e.message}`
  }
  if (e instanceof Error) return e.message
  return 'register_failed'
}

export default function RegisterPage() {
  const navigate = useNavigate()

  // 仅 dev/test/demo 才允许选角色；prod 强制 user
  const roleSelectable = useMemo(
    () => import.meta.env.DEV || import.meta.env.MODE !== 'production',
    [],
  )

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [role, setRole] = useState<RoleName>('user')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')

    if (!username.trim()) {
      setError('请输入用户名')
      return
    }
    if (password.length < MIN_PASSWORD_LEN) {
      setError(`密码至少 ${MIN_PASSWORD_LEN} 位`)
      return
    }
    if (password !== confirmPassword) {
      setError('两次输入的密码不一致')
      return
    }

    setBusy(true)
    try {
      const finalRole: RoleName = roleSelectable ? role : 'user'
      const resp = await registerAccount({
        username: username.trim(),
        password,
        display_name: displayName.trim() || undefined,
        role: finalRole,
      })
      const loggedInRole = resp.role
      useAuthStore.setState((s) => ({
        activeRole: loggedInRole,
        accessToken: resp.access_token,
        roleEpoch: s.roleEpoch + 1,
      }))
      navigate(HOME_PATH, { replace: true })
    } catch (err) {
      setError(registerErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative flex min-h-svh items-center justify-center overflow-hidden bg-background p-4">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--accent)_0%,_transparent_55%)]"
      />
      <Card className="relative w-full max-w-md border-border shadow-[var(--shadow-overlay)]">
        <CardHeader className="space-y-4 text-center">
          <BrandMark size="lg" className="justify-center" />
          <div className="space-y-1">
            <CardTitle className="text-lg font-semibold">创建账号</CardTitle>
            <CardDescription className="text-muted-foreground text-xs">
              注册后进入工作台（{HOME_PATH}）
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={onSubmit}>
            <div className="space-y-1.5">
              <Label htmlFor="reg-username">用户名</Label>
              <Input
                id="reg-username"
                type="text"
                autoComplete="username"
                placeholder="alice"
                value={username}
                onChange={(ev) => setUsername(ev.target.value)}
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="reg-password">密码</Label>
              <Input
                id="reg-password"
                type="password"
                autoComplete="new-password"
                placeholder={`至少 ${MIN_PASSWORD_LEN} 位`}
                value={password}
                onChange={(ev) => setPassword(ev.target.value)}
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="reg-confirm">确认密码</Label>
              <Input
                id="reg-confirm"
                type="password"
                autoComplete="new-password"
                placeholder="再次输入密码"
                value={confirmPassword}
                onChange={(ev) => setConfirmPassword(ev.target.value)}
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="reg-display">显示名（可选）</Label>
              <Input
                id="reg-display"
                type="text"
                autoComplete="off"
                placeholder="留空则用用户名"
                value={displayName}
                onChange={(ev) => setDisplayName(ev.target.value)}
              />
            </div>
            {roleSelectable ? (
              <div className="space-y-1.5">
                <Label htmlFor="reg-role">角色</Label>
                <Select
                  value={role}
                  onValueChange={(v) => setRole(v as RoleName)}
                >
                  <SelectTrigger id="reg-role" className="w-full">
                    <SelectValue placeholder="选择角色" />
                  </SelectTrigger>
                  <SelectContent>
                    {ROLES.map((r) => (
                      <SelectItem key={r} value={r}>
                        {r}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-muted-foreground text-xs">
                  仅 dev/test/demo 环境可选；生产构建强制 user。
                </p>
              </div>
            ) : null}
            {error ? (
              <p className="text-destructive text-xs" role="alert">
                {error}
              </p>
            ) : null}
            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? '注册中…' : '注册并登录'}
            </Button>
            <div className="text-muted-foreground text-xs text-center">
              已有账号？
              <Link
                to="/login"
                className="text-primary ml-1 underline-offset-2 hover:underline"
              >
                返回登录
              </Link>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
