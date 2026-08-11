import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { loginAccount } from '@/api/auth'
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
  /** JWT access token from password login (sessionStorage) */
  accessToken: string
  /** 角色切换计数；面板监听此值自动刷新（不 persist） */
  roleEpoch: number
  setKey: (role: RoleName, key: string) => void
  switchRole: (role: RoleName) => void
  clear: () => void
  clearActiveKey: () => void
  /** Bearer token if present; else active role API key (legacy /dev) */
  getAccessToken: () => string
  getActiveKey: () => string
  /**
   * 登录流：GET /health 探活成功后写入对应槽位（key 明文仅存 sessionStorage）。
   * 生产演进 TODO: httpOnly 会话 cookie，前端只存「已认证」标记。
   */
  loginWithKey: (role: RoleName, key: string) => Promise<void>
  /**
   * 账号密码登录：POST /api/auth/login 成功后写入 JWT（不写 api_key 槽）。
   */
  loginWithPassword: (username: string, password: string) => Promise<RoleName>
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      activeRole: 'user',
      keys: emptyKeys(),
      accessToken: '',
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
      clear: () =>
        set({
          activeRole: 'user',
          keys: emptyKeys(),
          accessToken: '',
          roleEpoch: 0,
        }),
      clearActiveKey: () => {
        const role = get().activeRole
        set((s) => ({
          keys: { ...s.keys, [role]: '' },
          accessToken: '',
        }))
      },
      getAccessToken: () => get().accessToken.trim(),
      getActiveKey: () => {
        const token = get().accessToken.trim()
        if (token) return token
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
          accessToken: '',
          roleEpoch: s.roleEpoch + 1,
        }))
      },
      loginWithPassword: async (username, password) => {
        const resp = await loginAccount({
          username: username.trim(),
          password,
        })
        const role = resp.role as RoleName
        set((s) => ({
          activeRole: role,
          accessToken: resp.access_token,
          roleEpoch: s.roleEpoch + 1,
        }))
        return role
      },
    }),
    {
      name: 'cg-auth',
      storage: createJSONStorage(() => sessionStorage),
      partialize: (s) => ({
        activeRole: s.activeRole,
        keys: s.keys,
        accessToken: s.accessToken,
      }),
    },
  ),
)
