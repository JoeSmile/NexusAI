/**
 * Product shell — topbar + content (no left sidebar).
 * Routes: /workspace/*, /admin/*
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { TokenUsageBar } from '@/components/agent/TokenUsageBar'
import { useAuthStore } from '@/stores/authStore'
import { useChatPrefsStore } from '@/stores/chatPrefsStore'
import { cn } from '@/lib/utils'

const TABS = [
  { to: '/workspace', end: true, label: '对话' },
  { to: '/workspace/dashboard', label: '工作台' },
  { to: '/workspace/knowledge', label: '知识库' },
  { to: '/workspace/content', label: '内容运营' },
  { to: '/workspace/social', label: '社媒对标' },
  { to: '/workspace/library', label: '内容库' },
] as const

export function AgentHomeShell() {
  const navigate = useNavigate()
  const clear = useAuthStore((s) => s.clear)
  const activeRole = useAuthStore((s) => s.activeRole)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const userMenuRef = useRef<HTMLDivElement>(null)

  const initials =
    activeRole === 'tenant_admin' ? '管' : activeRole === 'super_admin' ? '超' : '用'
  const isAdmin = activeRole === 'tenant_admin' || activeRole === 'super_admin'

  const logout = () => {
    setUserMenuOpen(false)
    clear()
    navigate('/login', { replace: true })
  }

  useEffect(() => {
    if (!userMenuOpen) return
    const onDoc = (e: MouseEvent) => {
      const el = userMenuRef.current
      if (el && !el.contains(e.target as Node)) setUserMenuOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setUserMenuOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [userMenuOpen])

  return (
    <div className="app agent-shell agent-shell--no-sidebar">
      <div className="main-container">
        <header className="topbar">
          <div className="topbar-left">
            <div className="topbar-brand">
              <span className="topbar-brand-mark" aria-hidden>
                N
              </span>
              <span className="topbar-brand-name">NexusAI</span>
            </div>
          </div>
          <div className="topbar-center">
            <nav className="topbar-nav">
              {TABS.map((t) => (
                <NavLink
                  key={t.to}
                  to={t.to}
                  end={'end' in t ? t.end : false}
                  className={({ isActive }) => cn('nav-tab', isActive && 'active')}
                >
                  {t.label}
                </NavLink>
              ))}
            </nav>
          </div>
          <div className="topbar-right">
            <TokenUsageBar />
            <button
              type="button"
              className="icon-btn context-config-btn"
              onClick={() => {
                const { contextOpen, setContextOpen } = useChatPrefsStore.getState()
                setContextOpen(!contextOpen)
              }}
              title="上下文与配置"
              aria-label="上下文与配置"
            >
              ⚙
            </button>
            {isAdmin ? (
              <button
                type="button"
                className="topbar-text-btn"
                onClick={() => navigate('/admin')}
                title="管理后台（租户/密钥/工作流等）"
              >
                管理后台
              </button>
            ) : null}
            <div className="topbar-user" ref={userMenuRef}>
              <button
                type="button"
                className="topbar-user-trigger"
                aria-expanded={userMenuOpen}
                aria-haspopup="menu"
                title={activeRole || '账号'}
                onClick={() => setUserMenuOpen((o) => !o)}
              >
                <span className="topbar-user-avatar">{initials}</span>
                <span className="topbar-user-role">{activeRole}</span>
              </button>
              {userMenuOpen ? (
                <div className="topbar-user-menu" role="menu">
                  <div className="topbar-user-menu-meta" title={activeRole || ''}>
                    {activeRole || '账号'}
                  </div>
                  <button
                    type="button"
                    role="menuitem"
                    className="topbar-user-menu-item"
                    onClick={logout}
                  >
                    退出登录
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        </header>

        <div className="content-area">
          <Outlet />
        </div>
      </div>
    </div>
  )
}

export function AgentAdminShell({ children }: { children?: ReactNode }) {
  const navigate = useNavigate()
  const clear = useAuthStore((s) => s.clear)
  return (
    <div
      className="agent-shell"
      style={{
        minHeight: '100svh',
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--color-gray-50)',
      }}
    >
      <header
        style={{
          height: 48,
          display: 'flex',
          alignItems: 'center',
          gap: 16,
          padding: '0 16px',
          borderBottom: '1px solid var(--color-gray-200)',
          background: 'var(--color-white)',
        }}
      >
        <button
          type="button"
          style={{ fontWeight: 600, color: 'var(--color-primary-700)' }}
          onClick={() => navigate('/workspace')}
        >
          NexusAI
        </button>
        <span style={{ fontSize: 12, color: 'var(--color-gray-400)' }}>管理后台</span>
        <nav
          style={{
            marginLeft: 16,
            display: 'flex',
            flexWrap: 'wrap',
            gap: 8,
            fontSize: 13,
          }}
        >
          {[
            ['/admin', '概览'],
            ['/admin/workflows', '工作流'],
            ['/admin/org', '组织'],
            ['/admin/audit', '审计'],
            ['/admin/billing', '账单'],
            ['/admin/keys', '凭证'],
          ].map(([path, label]) => (
            <NavLink
              key={path}
              to={path}
              end={path === '/admin'}
              className={({ isActive }) =>
                cn(
                  'rounded-md px-2 py-1',
                  isActive ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100',
                )
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <button
          type="button"
          style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--color-gray-500)' }}
          onClick={() => {
            clear()
            navigate('/login')
          }}
        >
          退出
        </button>
      </header>
      <main style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        {children ?? <Outlet />}
      </main>
    </div>
  )
}
