import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import type { RoleName } from '@/types/api'

export const ROLES: RoleName[] = [
  'user',
  'tenant_admin',
  'auditor',
  'super_admin',
]

type KeysByRole = Record<RoleName, string>

const emptyKeys = (): KeysByRole => ({
  user: '',
  tenant_admin: '',
  auditor: '',
  super_admin: '',
})

export interface AuthState {
  activeRole: RoleName
  keys: KeysByRole
  /** 角色切换计数；面板监听此值自动刷新（不 persist） */
  roleEpoch: number
  setKey: (role: RoleName, key: string) => void
  switchRole: (role: RoleName) => void
  clear: () => void
  clearActiveKey: () => void
  getActiveKey: () => string
  /**
   * 登录流：GET /health 探活成功后写入对应槽位（key 明文仅存 sessionStorage）。
   * 生产演进 TODO: httpOnly 会话 cookie，前端只存「已认证」标记。
   */
  loginWithKey: (role: RoleName, key: string) => Promise<void>
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      activeRole: 'user',
      keys: emptyKeys(),
      roleEpoch: 0,
      setKey: (role, key) =>
        set((s) => ({
          keys: { ...s.keys, [role]: key.trim() },
        })),
      switchRole: (role) =>
        set((s) => ({
          activeRole: role,
          roleEpoch: s.activeRole === role ? s.roleEpoch : s.roleEpoch + 1,
        })),
      clear: () => set({ activeRole: 'user', keys: emptyKeys(), roleEpoch: 0 }),
      clearActiveKey: () => {
        const role = get().activeRole
        set((s) => ({ keys: { ...s.keys, [role]: '' } }))
      },
      getActiveKey: () => {
        const { activeRole, keys } = get()
        return keys[activeRole] || ''
      },
      loginWithKey: async (role, key) => {
        const trimmed = key.trim()
        if (!trimmed) {
          throw new Error('api_key_required')
        }
        const res = await fetch('/health', {
          headers: { 'X-API-Key': trimmed },
        })
        if (!res.ok) {
          throw new Error(`health_failed:${res.status}`)
        }
        set((s) => ({
          activeRole: role,
          keys: { ...s.keys, [role]: trimmed },
          roleEpoch: s.roleEpoch + 1,
        }))
      },
    }),
    {
      name: 'cg-auth',
      storage: createJSONStorage(() => sessionStorage),
      partialize: (s) => ({ activeRole: s.activeRole, keys: s.keys }),
    },
  ),
)
