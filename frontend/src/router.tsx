import { Navigate, Outlet, createBrowserRouter, useLocation } from 'react-router-dom'

import { AppShell } from '@/components/layout/AppShell'
import LoginPage from '@/pages/login'
import AdminPanel from '@/pages/panels/admin'
import ChatPanel from '@/pages/panels/chat'
import PlaceholderPanel from '@/pages/panels/PlaceholderPanel'
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
  {
    element: <RequireAuth />,
    children: [
      {
        path: '/',
        element: <AppShell />,
        children: [
          { index: true, element: <Navigate to="/panels/chat" replace /> },
          { path: 'panels/chat', element: <ChatPanel /> },
          { path: 'panels/rag', element: <PlaceholderPanel /> },
          { path: 'panels/admin', element: <AdminPanel /> },
          { path: 'panels/audit', element: <PlaceholderPanel /> },
          { path: 'panels/agent', element: <PlaceholderPanel /> },
          { path: 'panels/eval', element: <PlaceholderPanel /> },
          { path: 'panels/performance', element: <PlaceholderPanel /> },
          { path: 'panels/capabilities', element: <PlaceholderPanel /> },
        ],
      },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
])
