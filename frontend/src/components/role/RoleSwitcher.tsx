import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useForbiddenStore } from '@/stores/forbiddenStore'
import { ROLES, useAuthStore } from '@/stores/authStore'
import type { RoleName } from '@/types/api'
import { cn } from '@/lib/utils'

/** 角色徽章色：user 灰 / tadmin 蓝 / auditor 青(避紫) / super 橙 */
const ROLE_BADGE: Record<RoleName, string> = {
  user: 'bg-secondary text-muted-foreground',
  tenant_admin: 'bg-[var(--primary)] text-white',
  auditor: 'bg-[var(--chart-4)] text-white',
  super_admin: 'bg-[var(--warning)] text-white',
}

const ROLE_SHORT: Record<RoleName, string> = {
  user: 'user',
  tenant_admin: 'tadmin',
  auditor: 'auditor',
  super_admin: 'super',
}

export function RoleSwitcher() {
  const activeRole = useAuthStore((s) => s.activeRole)
  const keys = useAuthStore((s) => s.keys)
  const switchRole = useAuthStore((s) => s.switchRole)
  const clearForbidden = useForbiddenStore((s) => s.clear)

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="gap-2"
          aria-label="切换角色"
        >
          <span
            className={cn(
              'rounded-full px-2 py-0.5 text-xs font-medium',
              ROLE_BADGE[activeRole],
            )}
          >
            {ROLE_SHORT[activeRole]}
          </span>
          <span className="text-muted-foreground text-xs">切换</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        {ROLES.map((role) => {
          const configured = Boolean(keys[role])
          return (
            <DropdownMenuItem
              key={role}
              onClick={() => {
                switchRole(role)
                clearForbidden()
              }}
              className="flex items-center justify-between gap-2"
            >
              <span className="flex items-center gap-2">
                <Badge className={cn('rounded-full', ROLE_BADGE[role])}>
                  {ROLE_SHORT[role]}
                </Badge>
                {role === activeRole ? (
                  <span className="text-xs text-primary">当前</span>
                ) : null}
              </span>
              <span className="text-muted-foreground text-xs">
                {configured ? '已配置' : '未配置'}
              </span>
            </DropdownMenuItem>
          )
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function ForbiddenBanner() {
  const last = useForbiddenStore((s) => s.last)
  if (!last) return null
  const need = last.needed || last.message
  return (
    <div
      role="alert"
      className="mb-3 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
    >
      该角色无权限{need ? `（需 ${need}）` : ''} — 请用右上角切换角色后重试
    </div>
  )
}
