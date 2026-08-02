import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiGet } from '@/api/http'
import { useAuthStore } from '@/stores/authStore'
import { useForbiddenStore } from '@/stores/forbiddenStore'

describe('RoleSwitcher key + 403 (frame for 30.26 UI)', () => {
  beforeEach(() => {
    useAuthStore.setState({
      activeRole: 'user',
      keys: {
        user: 'k-user',
        tenant_admin: '',
        auditor: '',
        super_admin: 'k-super',
      },
    })
    useForbiddenStore.getState().clear()
    vi.unstubAllGlobals()
  })

  it('switchRole changes X-API-Key on next request', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ([]),
    })
    vi.stubGlobal('fetch', fetchMock)

    useAuthStore.getState().switchRole('super_admin')
    await apiGet('/api/admin/api-keys')
    const headers = fetchMock.mock.calls[0][1].headers as Headers
    expect(headers.get('X-API-Key')).toBe('k-super')
  })

  it('403 sets forbidden store for highlight', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 403,
        clone: () => ({
          json: async () => ({
            detail: { code: 'AUTH_002', message: 'insufficient_permissions' },
          }),
        }),
      }),
    )
    await expect(apiGet('/api/admin/api-keys')).rejects.toMatchObject({
      forbidden: true,
    })
    const last = useForbiddenStore.getState().last
    expect(last?.code).toBe('AUTH_002')
    expect(last?.path).toBe('/api/admin/api-keys')
  })
})
