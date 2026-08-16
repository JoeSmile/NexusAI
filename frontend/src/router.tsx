import { Navigate, Outlet, createBrowserRouter, useLocation } from 'react-router-dom'

import { RequireRoles } from '@/components/auth/RequireRoles'
import { AppShell } from '@/components/layout/AppShell'
import { KEYS_ROLES, ORG_ROLES } from '@/lib/navAccess'
import { HOME_PATH, PANEL_REDIRECTS } from '@/lib/routes'
import LoginPage from '@/pages/login'
import RegisterPage from '@/pages/register'
import AdminPanel from '@/pages/panels/admin'
import AgentPanel from '@/pages/panels/agent'
import AuditPanel from '@/pages/panels/audit'
import ChatPanel from '@/pages/panels/chat'
import ContentStudioPage from '@/pages/content/ContentStudio'
import EvalPanel from '@/pages/panels/eval'
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
  if (!key && !accessToken) {
    const next = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?next=${next}`} replace />
  }
  return <Outlet />
}

function PanelRedirect({ from }: { from: string }) {
  const to = PANEL_REDIRECTS[from] ?? HOME_PATH
  return <Navigate to={to} replace />
}

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  { path: '/register', element: <RegisterPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        path: '/',
        element: <AppShell />,
        children: [
          { index: true, element: <Navigate to={HOME_PATH} replace /> },
          { path: 'workspace/chat', element: <ChatPanel /> },
          { path: 'workspace/content', element: <ContentStudioPage /> },
          { path: 'workspace/agent', element: <AgentPanel /> },
          { path: 'workspace/eval', element: <EvalPanel /> },
          { path: 'workflows', element: <WorkflowListPage /> },
          { path: 'workflows/:id/edit', element: <WorkflowEditorPage /> },
          { path: 'workflows/:id/runs', element: <RunListPage /> },
          { path: 'runs', element: <RunListPage /> },
          { path: 'runs/:runId', element: <RunDetailPage /> },
          { path: 'approvals', element: <ApprovalInboxPage /> },
          { path: 'notifications', element: <NotificationsPage /> },
          { path: 'knowledge', element: <RagPanel /> },
          {
            element: <RequireRoles allow={ORG_ROLES} />,
            children: [
              { path: 'governance/org', element: <OrgTreePage /> },
            ],
          },
          { path: 'governance/audit', element: <AuditPanel /> },
          { path: 'governance/capabilities', element: <CapabilitiesPanel /> },
          { path: 'governance/performance', element: <PerformancePanel /> },
          {
            element: <RequireRoles allow={KEYS_ROLES} />,
            children: [
              { path: 'governance/keys', element: <AdminPanel /> },
            ],
          },
          // 旧 /panels/* 兼容（目标路径仍经上表守卫）
          { path: 'panels/chat', element: <PanelRedirect from="/panels/chat" /> },
          { path: 'panels/agent', element: <PanelRedirect from="/panels/agent" /> },
          { path: 'panels/eval', element: <PanelRedirect from="/panels/eval" /> },
          { path: 'panels/rag', element: <PanelRedirect from="/panels/rag" /> },
          { path: 'panels/admin', element: <PanelRedirect from="/panels/admin" /> },
          { path: 'panels/audit', element: <PanelRedirect from="/panels/audit" /> },
          {
            path: 'panels/capabilities',
            element: <PanelRedirect from="/panels/capabilities" />,
          },
          {
            path: 'panels/performance',
            element: <PanelRedirect from="/panels/performance" />,
          },
        ],
      },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
])
