import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, apiFetch, apiGet, formatApiError } from './http'
import { useAuthStore } from '@/stores/authStore'

describe('api http', () => {
  beforeEach(() => {
    sessionStorage.clear()
    useAuthStore.setState({
      activeRole: 'user',
      keys: {
        user: 'test-key',
        tenant_admin: '',
        auditor: '',
        super_admin: '',
      },
      roleEpoch: 0,
    })
    vi.unstubAllGlobals()
  })

  it('attaches X-API-Key from active slot', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await apiGet('/api/capabilities')
    expect(fetchMock).toHaveBeenCalled()
    const headers = fetchMock.mock.calls[0][1].headers as Headers
    expect(headers.get('X-API-Key')).toBe('test-key')
  })

  it('401 clears active key and redirects to login', async () => {
    useAuthStore.getState().setKey('user', 'dead')
    const assign = vi.fn()
    vi.stubGlobal('location', {
      pathname: '/panels/chat',
      search: '',
      assign,
    })
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        clone: () => ({
          json: async () => ({
            detail: { code: 'AUTH_001', message: 'invalid_key' },
          }),
        }),
        json: async () => ({
          detail: { code: 'AUTH_001', message: 'invalid_key' },
        }),
      }),
    )

    await expect(apiGet('/api/capabilities')).rejects.toMatchObject({
      status: 401,
      code: 'AUTH_001',
    })
    expect(useAuthStore.getState().keys.user).toBe('')
    expect(assign).toHaveBeenCalledWith(
      expect.stringMatching(/^\/login\?next=/),
    )
  })

  it('403 returns structured forbidden + needed', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 403,
        clone: () => ({
          json: async () => ({
            error: {
              code: 'AUTH_002',
              message: 'insufficient_permissions',
              detail: 'admin:*',
            },
          }),
        }),
      }),
    )

    try {
      await apiFetch('/api/admin/x')
      expect.fail('should throw')
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError)
      const err = e as ApiError
      expect(err.forbidden).toBe(true)
      expect(err.needed).toBe('admin:*')
      expect(err.code).toBe('AUTH_002')
    }
  })

  it('formatApiError prefers forbidden needed permission', () => {
    const e = new ApiError({
      status: 403,
      code: 'AUTH_002',
      message: 'forbidden',
      forbidden: true,
      needed: 'admin:*',
    })
    expect(formatApiError(e, 'admin:approve')).toBe('该角色无权限（需 admin:*）')
    expect(formatApiError(new Error('boom'))).toBe('boom')
  })

  it('missing key redirects without calling fetch', async () => {
    useAuthStore.setState({
      keys: {
        user: '',
        tenant_admin: '',
        auditor: '',
        super_admin: '',
      },
    })
    const assign = vi.fn()
    const fetchMock = vi.fn()
    vi.stubGlobal('location', { pathname: '/', search: '', assign })
    vi.stubGlobal('fetch', fetchMock)

    await expect(apiGet('/api/capabilities')).rejects.toMatchObject({
      status: 401,
      code: 'AUTH_001',
    })
    expect(fetchMock).not.toHaveBeenCalled()
    expect(assign).toHaveBeenCalledWith(
      expect.stringMatching(/^\/login\?next=/),
    )
  })
})
