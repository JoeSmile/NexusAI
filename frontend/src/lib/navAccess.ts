import type { RoleName } from '@/types/api'

/** 与侧栏「治理」过滤同源；路由守卫复用，避免只藏导航。 */
export const ORG_ROLES: RoleName[] = [
  'tenant_admin',
  'auditor',
  'super_admin',
]

export const KEYS_ROLES: RoleName[] = ['tenant_admin', 'super_admin']

export const CONSOLE_ROLES: RoleName[] = ['tenant_admin', 'super_admin']

export function roleAllowed(
  role: RoleName,
  allow: readonly RoleName[] | undefined,
): boolean {
  if (!allow || allow.length === 0) return true
  return allow.includes(role)
}
