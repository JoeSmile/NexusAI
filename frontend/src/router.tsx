import { Navigate, Outlet, createBrowserRouter, useLocation } from 'react-router-dom'

import { AppShell } from '@/components/layout/AppShell'
import LoginPage from '@/pages/login'
import RegisterPage from '@/pages/register'
import AdminPanel from '@/pages/panels/admin'
import AgentPanel from '@/pages/panels/agent'
import AuditPanel from '@/pages/panels/audit'
import ChatPanel from '@/pages/panels/chat'
import EvalPanel from '@/pages/panels/eval'
import CapabilitiesPanel from '@/pages/panels/capabilities'
import PerformancePanel from '@/pages/panels/performance'
import RagPanel from '@/pages/panels/rag'
import { useAuthStore } from '@/stores/authStore'

function RequireAuth() {
  const key = useAuthStore((s) => s.keys[s.activeRole])
  const location = useLocation()
  if (!key) {
    const next = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?next=${next}`} replace />
  }
  return <Outlet />
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
          { index: true, element: <Navigate to="/panels/chat" replace /> },
          { path: 'panels/chat', element: <ChatPanel /> },
          { path: 'panels/rag', element: <RagPanel /> },
          { path: 'panels/admin', element: <AdminPanel /> },
          { path: 'panels/audit', element: <AuditPanel /> },
          { path: 'panels/agent', element: <AgentPanel /> },
          { path: 'panels/eval', element: <EvalPanel /> },
          { path: 'panels/performance', element: <PerformancePanel /> },
          { path: 'panels/capabilities', element: <CapabilitiesPanel /> },
        ],
      },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
])
