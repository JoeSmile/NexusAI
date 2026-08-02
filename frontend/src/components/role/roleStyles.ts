import type { RoleName } from '@/types/api'

/** 角色徽章色：user 灰 / tadmin 蓝 / auditor 青 / super 橙 */
export const ROLE_BADGE: Record<RoleName, string> = {
  user: 'bg-secondary text-muted-foreground',
  tenant_admin: 'bg-[var(--primary)] text-white',
  auditor: 'bg-[var(--chart-4)] text-white',
  super_admin: 'bg-[var(--warning)] text-white',
}

export const ROLE_SHORT: Record<RoleName, string> = {
  user: 'user',
  tenant_admin: 'tadmin',
  auditor: 'auditor',
  super_admin: 'super',
}
