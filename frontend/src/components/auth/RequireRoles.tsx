import { Navigate, Outlet } from 'react-router-dom'

import { HOME_PATH } from '@/lib/routes'
import { roleAllowed } from '@/lib/navAccess'
import { useAuthStore } from '@/stores/authStore'
import type { RoleName } from '@/types/api'

/** 侧栏隐藏不够：直开 URL 也要拦（Wave S Important B）。 */
export function RequireRoles({ allow }: { allow: readonly RoleName[] }) {
  const role = useAuthStore((s) => s.activeRole)
  if (!roleAllowed(role, allow)) {
    return <Navigate to={HOME_PATH} replace />
  }
  return <Outlet />
}
