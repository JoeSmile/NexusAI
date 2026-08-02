import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from './authStore'

describe('authStore', () => {
  beforeEach(() => {
    sessionStorage.clear()
    try {
      localStorage.clear()
    } catch {
      /* jsdom/node may stub localStorage without clear */
    }
    useAuthStore.setState({
      activeRole: 'user',
      keys: {
        user: '',
        tenant_admin: '',
        auditor: '',
        super_admin: '',
      },
    })
    useAuthStore.persist.clearStorage()
  })

  it('keeps four key slots independent across switchRole', () => {
    const { setKey, switchRole, getActiveKey } = useAuthStore.getState()
    setKey('user', 'k-user')
    setKey('tenant_admin', 'k-admin')
    setKey('auditor', 'k-auditor')
    setKey('super_admin', 'k-super')

    expect(useAuthStore.getState().keys.user).toBe('k-user')
    expect(useAuthStore.getState().keys.tenant_admin).toBe('k-admin')

    switchRole('tenant_admin')
    expect(getActiveKey()).toBe('k-admin')
    expect(useAuthStore.getState().keys.user).toBe('k-user')

    switchRole('auditor')
    expect(getActiveKey()).toBe('k-auditor')
    expect(useAuthStore.getState().keys.super_admin).toBe('k-super')
  })

  it('persists to sessionStorage (P0: not localStorage)', async () => {
    useAuthStore.getState().setKey('user', 'sess-key')
    useAuthStore.getState().switchRole('user')
    await vi.waitFor(() => {
      const raw = sessionStorage.getItem('cg-auth')
      expect(raw).toBeTruthy()
      expect(raw).toContain('sess-key')
    })
    // 存储键名与 createJSONStorage(() => sessionStorage) 约定一致
    expect(useAuthStore.persist.getOptions().name).toBe('cg-auth')
  })

  it('loginWithKey probes /health then stores slot', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 })
    vi.stubGlobal('fetch', fetchMock)

    await useAuthStore.getState().loginWithKey('user', '  abc  ')
    expect(fetchMock).toHaveBeenCalledWith(
      '/health',
      expect.objectContaining({
        headers: { 'X-API-Key': 'abc' },
      }),
    )
    expect(useAuthStore.getState().keys.user).toBe('abc')
    expect(useAuthStore.getState().activeRole).toBe('user')

    vi.unstubAllGlobals()
  })
})
