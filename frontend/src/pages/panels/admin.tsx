import { useEffect, useState } from 'react'

import { apiGet, ApiError } from '@/api/http'
import { ForbiddenBanner } from '@/components/role/RoleSwitcher'
import { useAuthStore } from '@/stores/authStore'

/** Admin 面板雏形：拉 /api/admin/api-keys 以演示 403 高亮（30.14）。 */
export default function AdminPanel() {
  const role = useAuthStore((s) => s.activeRole)
  const key = useAuthStore((s) => s.keys[s.activeRole])
  const [info, setInfo] = useState('')
  const [err, setErr] = useState('')

  useEffect(() => {
    let cancelled = false
    setInfo('')
    setErr('')
    ;(async () => {
      try {
        const data = await apiGet<unknown>('/api/admin/api-keys')
        if (!cancelled) setInfo(JSON.stringify(data).slice(0, 200))
      } catch (e) {
        if (cancelled) return
        if (e instanceof ApiError && e.forbidden) {
          setErr(`该角色无权限（需 ${e.needed || 'admin:*'}）`)
        } else {
          setErr(e instanceof Error ? e.message : String(e))
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [role, key])

  return (
    <div className="space-y-2">
      <h1 className="text-xl font-semibold">Admin</h1>
      <p className="text-muted-foreground text-xs">
        当前角色 <code>{role}</code> — 请求 GET /api/admin/api-keys
      </p>
      <ForbiddenBanner />
      {err ? (
        <p className="text-destructive text-sm" role="alert">
          {err}
        </p>
      ) : null}
      {info ? (
        <pre className="overflow-auto rounded-lg border border-border bg-card p-2 text-xs">
          {info}
        </pre>
      ) : null}
    </div>
  )
}
