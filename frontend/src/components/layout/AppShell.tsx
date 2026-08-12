import { useEffect, useMemo, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { BrandMark } from '@/components/brand/BrandMark'
import { RoleSwitcher } from '@/components/role/RoleSwitcher'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { KEYS_ROLES, ORG_ROLES, roleAllowed } from '@/lib/navAccess'
import { useAuthStore } from '@/stores/authStore'
import type { RoleName } from '@/types/api'
import { cn } from '@/lib/utils'

type AppEnv = 'dev' | 'test' | 'demo'

type NavItem = { to: string; label: string; roles?: RoleName[] }

type NavGroup = { id: string; label: string; items: NavItem[] }

const NAV_GROUPS: NavGroup[] = [
  {
    id: 'workspace',
    label: '工作台',
    items: [
      { to: '/workspace/chat', label: '对话' },
      { to: '/workspace/agent', label: 'Agent' },
      { to: '/workspace/eval', label: '评估' },
    ],
  },
  {
    id: 'workflows',
    label: '工作流',
    items: [{ to: '/workflows', label: '流程' }],
  },
  {
    id: 'approvals',
    label: '审批',
    items: [{ to: '/approvals', label: '待办' }],
  },
  {
    id: 'knowledge',
    label: '知识库',
    items: [{ to: '/knowledge', label: 'RAG' }],
  },
  {
    id: 'governance',
    label: '治理',
    items: [
      {
        to: '/governance/org',
        label: '组织',
        roles: ORG_ROLES,
      },
      { to: '/governance/audit', label: '审计' },
      { to: '/governance/capabilities', label: '能力' },
      { to: '/governance/performance', label: '性能' },
      {
        to: '/governance/keys',
        label: 'API Keys',
        roles: KEYS_ROLES,
      },
    ],
  },
]

function envBadgeClass(env: AppEnv): string {
  if (env === 'test') return 'bg-primary text-primary-foreground'
  if (env === 'demo') return 'bg-[var(--success)] text-white'
  return 'bg-secondary text-muted-foreground'
}

function resolveEnv(raw: unknown): AppEnv {
  const v = String(raw || '').toLowerCase()
  if (v === 'test' || v === 'demo' || v === 'dev') return v
  return 'dev'
}

function itemVisible(item: NavItem, role: RoleName): boolean {
  return roleAllowed(role, item.roles)
}

export function AppShell() {
  const navigate = useNavigate()
  const activeRole = useAuthStore((s) => s.activeRole)
  const clear = useAuthStore((s) => s.clear)
  const [env, setEnv] = useState<AppEnv>('dev')

  useEffect(() => {
    const fromVite = import.meta.env.VITE_APP_ENV
    if (fromVite) {
      setEnv(resolveEnv(fromVite))
      return
    }
    fetch('/cg-meta')
      .then((r) => (r.ok ? r.json() : null))
      .then((j: { environment?: string; env?: string } | null) => {
        setEnv(resolveEnv(j?.environment ?? j?.env ?? 'dev'))
      })
      .catch(() => setEnv('dev'))
  }, [])

  const groups = useMemo(() => {
    return NAV_GROUPS.map((g) => ({
      ...g,
      items: g.items.filter((it) => itemVisible(it, activeRole)),
    })).filter((g) => g.items.length > 0)
  }, [activeRole])

  return (
    <div className="flex min-h-svh flex-col bg-background">
      <header className="flex h-12 items-center gap-3 border-b border-border bg-card px-4">
        <BrandMark size="sm" />
        <Badge className={cn('rounded-full text-xs', envBadgeClass(env))}>
          {env}
        </Badge>
        <div className="text-muted-foreground ml-auto flex items-center gap-3 text-xs">
          <RoleSwitcher />
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button type="button" variant="ghost" size="sm" aria-label="用户菜单">
                菜单
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem disabled>角色 · {activeRole}</DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => {
                  clear()
                  navigate('/login', { replace: true })
                }}
              >
                退出并清空槽位
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>
      <div className="flex min-h-0 flex-1">
        <aside className="w-56 shrink-0 border-r border-border bg-sidebar px-2 py-3">
          <nav className="flex flex-col gap-4">
            {groups.map((group) => (
              <div key={group.id}>
                <div className="text-muted-foreground mb-1.5 px-2 text-[11px] font-medium tracking-wide uppercase">
                  {group.label}
                </div>
                <div className="flex flex-col gap-0.5">
                  {group.items.map((item) => (
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
                </div>
              </div>
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
