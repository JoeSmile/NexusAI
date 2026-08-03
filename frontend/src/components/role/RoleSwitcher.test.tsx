import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiGet } from '@/api/http'
import { ForbiddenBanner, RoleSwitcher } from '@/components/role/RoleSwitcher'
import { useAuthStore } from '@/stores/authStore'
import { useForbiddenStore } from '@/stores/forbiddenStore'

describe('RoleSwitcher UI', () => {
  beforeEach(() => {
    useAuthStore.setState({
      activeRole: 'user',
      keys: {
        user: 'k-user',
        tenant_admin: 'k-ta',
        auditor: '',
        super_admin: 'k-super',
      },
      roleEpoch: 0,
    })
    useForbiddenStore.getState().clear()
    vi.unstubAllGlobals()
  })

  it('renders switcher and switches role on menu click', async () => {
    const user = userEvent.setup()
    render(<RoleSwitcher />)
    await user.click(screen.getByRole('button', { name: '切换角色' }))
    const items = await screen.findAllByText('super')
    await user.click(items[items.length - 1])
    expect(useAuthStore.getState().activeRole).toBe('super_admin')
  })

  it('ForbiddenBanner shows after 403 and clears on role switch', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 403,
        clone: () => ({
          json: async () => ({
            detail: {
              code: 'AUTH_002',
              message: 'insufficient_permissions',
              detail: 'admin:*',
            },
          }),
        }),
      }),
    )
    await expect(apiGet('/api/admin/api-keys')).rejects.toMatchObject({ forbidden: true })

    const { rerender } = render(
      <>
        <RoleSwitcher />
        <ForbiddenBanner />
      </>,
    )
    expect(screen.getByRole('alert')).toHaveTextContent(/该角色无权限/)
    expect(screen.getByRole('alert')).toHaveTextContent(/admin:\*/)

    useAuthStore.getState().switchRole('super_admin')
    useForbiddenStore.getState().clear()
    rerender(
      <>
        <RoleSwitcher />
        <ForbiddenBanner />
      </>,
    )
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('switchRole causes next apiGet to send the new X-API-Key', async () => {
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
    expect(useAuthStore.getState().activeRole).toBe('super_admin')
  })
})
