import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'

import { Badge } from '@/components/ui/badge'
import { RoleSwitcher } from '@/components/role/RoleSwitcher'
import { useAuthStore } from '@/stores/authStore'
import { cn } from '@/lib/utils'

type AppEnv = 'dev' | 'test' | 'demo'

const NAV = [
  { to: '/panels/chat', label: 'Chat' },
  { to: '/panels/rag', label: 'RAG' },
  { to: '/panels/admin', label: 'Admin' },
  { to: '/panels/audit', label: 'Audit' },
  { to: '/panels/agent', label: 'Agent' },
  { to: '/panels/eval', label: 'Eval' },
  { to: '/panels/performance', label: '性能' },
  { to: '/panels/capabilities', label: '能力' },
] as const

function envBadgeClass(env: AppEnv): string {
  if (env === 'test') return 'bg-[var(--primary)] text-white'
  if (env === 'demo') return 'bg-[var(--success)] text-white'
  return 'bg-secondary text-muted-foreground' // dev=灰
}

function resolveEnv(raw: unknown): AppEnv {
  const v = String(raw || '').toLowerCase()
  if (v === 'test' || v === 'demo' || v === 'dev') return v
  return 'dev'
}

export function AppShell() {
  const activeRole = useAuthStore((s) => s.activeRole)
  const [env, setEnv] = useState<AppEnv>('dev')

  useEffect(() => {
    const fromVite = import.meta.env.VITE_APP_ENV
    if (fromVite) {
      setEnv(resolveEnv(fromVite))
      return
    }
    // Vite 下 `/` 是 SPA；经 /cg-meta 反代到后端根（见 vite.config）
    fetch('/cg-meta')
      .then((r) => (r.ok ? r.json() : null))
      .then((j: { environment?: string; env?: string } | null) => {
        setEnv(resolveEnv(j?.environment ?? j?.env ?? 'dev'))
      })
      .catch(() => setEnv('dev'))
  }, [])

  return (
    <div className="flex min-h-svh flex-col bg-background">
      <header className="flex h-12 items-center gap-3 border-b border-border bg-card px-4">
        <div className="text-sm font-semibold text-foreground">ContextGate</div>
        <Badge className={cn('rounded-full text-xs', envBadgeClass(env))}>
          {env}
        </Badge>
        <div className="text-muted-foreground ml-auto flex items-center gap-3 text-xs">
          <RoleSwitcher />
          <span className="hidden sm:inline">测试 FE · {activeRole}</span>
        </div>
      </header>
      <div className="flex min-h-0 flex-1">
        <aside className="w-52 shrink-0 border-r border-border bg-sidebar px-2 py-3">
          <div className="text-muted-foreground mb-2 px-2 text-xs">演示区</div>
          <nav className="flex flex-col gap-0.5">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    'rounded-md px-2 py-1.5 text-sm text-sidebar-foreground',
                    isActive
                      ? 'bg-sidebar-accent font-medium text-sidebar-accent-foreground'
                      : 'hover:bg-muted',
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </aside>
        <main className="min-w-0 flex-1 overflow-auto p-4">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
