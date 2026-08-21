import { Navigate, Outlet, createBrowserRouter, useLocation } from 'react-router-dom'
import { useEffect, useState } from 'react'

import { RequireRoles } from '@/components/auth/RequireRoles'
import {
  AgentAdminShell,
  AgentHomeShell,
} from '@/layouts/AgentShell'
import { KEYS_ROLES, ORG_ROLES } from '@/lib/navAccess'
import { HOME_PATH, PANEL_REDIRECTS } from '@/lib/routes'
import AgentLoginPage from '@/pages/agent/LoginPage'
import AdminHomePage from '@/pages/agent/AdminHome'
import HomeChatPage from '@/pages/agent/HomeChat'
import WorkspaceDashboard from '@/pages/agent/WorkspaceDashboard'
import RootLanding from '@/pages/marketing/Landing'
import ContentLibraryPage from '@/pages/content/ContentLibrary'
import ContentStudioPage from '@/pages/content/ContentStudio'
import SocialBenchmarkPage from '@/pages/content/SocialBenchmark'
import AdminPanel from '@/pages/panels/admin'
import AuditPanel from '@/pages/panels/audit'
import CapabilitiesPanel from '@/pages/panels/capabilities'
import PerformancePanel from '@/pages/panels/performance'
import OrgTreePage from '@/pages/admin/OrgTree'
import RagPanel from '@/pages/panels/rag'
import WorkflowListPage from '@/pages/workflows/WorkflowList'
import WorkflowEditorPage from '@/pages/workflows/WorkflowEditor'
import RunListPage from '@/pages/workflows/RunList'
import RunDetailPage from '@/pages/workflows/RunDetail'
import ApprovalInboxPage from '@/pages/approvals/ApprovalInbox'
import NotificationsPage from '@/pages/notifications/NotificationsPage'
import { useAuthStore } from '@/stores/authStore'

function RequireAuth() {
  const key = useAuthStore((s) => s.keys[s.activeRole])
  const accessToken = useAuthStore((s) => s.accessToken)
  const location = useLocation()
  const [hydrated, setHydrated] = useState(() => useAuthStore.persist.hasHydrated())

  useEffect(() => {
    if (hydrated) return
    const unsub = useAuthStore.persist.onFinishHydration(() => setHydrated(true))
    if (useAuthStore.persist.hasHydrated()) setHydrated(true)
    return unsub
  }, [hydrated])

  if (!hydrated) {
    return (
      <div className="flex min-h-svh items-center justify-center text-sm text-slate-500">
        加载会话…
      </div>
    )
  }

  if (!key && !accessToken) {
    const next = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?next=${next}`} replace />
  }
  return <Outlet />
}

function LegacyRedirect({ from }: { from: string }) {
  const to = PANEL_REDIRECTS[from] ?? HOME_PATH
  return <Navigate to={to} replace />
}

export const router = createBrowserRouter([
  { path: '/', element: <RootLanding /> },
  { path: '/login', element: <AgentLoginPage /> },
  // Sales-led: no public self-register; accounts provisioned by ops
  { path: '/register', element: <Navigate to="/login" replace /> },
  {
    element: <RequireAuth />,
    children: [
      {
        path: '/workspace',
        element: <AgentHomeShell />,
        children: [
          { index: true, element: <HomeChatPage /> },
          { path: 'dashboard', element: <WorkspaceDashboard /> },
          { path: 'knowledge', element: <RagPanel /> },
          { path: 'content', element: <ContentStudioPage /> },
          { path: 'social', element: <SocialBenchmarkPage /> },
          { path: 'library', element: <ContentLibraryPage /> },
        ],
      },
      {
        path: '/admin',
        element: <AgentAdminShell />,
        children: [
          { index: true, element: <AdminHomePage /> },
          { path: 'knowledge', element: <Navigate to="/workspace/knowledge" replace /> },
          { path: 'workflows', element: <WorkflowListPage /> },
          { path: 'workflows/:id/edit', element: <WorkflowEditorPage /> },
          { path: 'workflows/:id/runs', element: <RunListPage /> },
          { path: 'runs', element: <RunListPage /> },
          { path: 'runs/:runId', element: <RunDetailPage /> },
          { path: 'approvals', element: <ApprovalInboxPage /> },
          { path: 'notifications', element: <NotificationsPage /> },
          {
            element: <RequireRoles allow={ORG_ROLES} />,
            children: [{ path: 'org', element: <OrgTreePage /> }],
          },
          { path: 'audit', element: <AuditPanel /> },
          { path: 'capabilities', element: <CapabilitiesPanel /> },
          { path: 'performance', element: <PerformancePanel /> },
          {
            element: <RequireRoles allow={KEYS_ROLES} />,
            children: [{ path: 'keys', element: <AdminPanel /> }],
          },
        ],
      },
      { path: 'panels/chat', element: <LegacyRedirect from="/panels/chat" /> },
      { path: 'knowledge', element: <Navigate to="/workspace/knowledge" replace /> },
      { path: 'workflows/*', element: <Navigate to="/admin/workflows" replace /> },
      { path: 'governance/*', element: <Navigate to="/admin" replace /> },
    ],
  },
  { path: '*', element: <Navigate to={HOME_PATH} replace /> },
])
