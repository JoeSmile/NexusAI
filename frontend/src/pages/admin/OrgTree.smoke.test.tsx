import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import OrgTreePage from '@/pages/admin/OrgTree'
import { useAuthStore } from '@/stores/authStore'
import { useForbiddenStore } from '@/stores/forbiddenStore'

describe('OrgTree page smoke', () => {
  beforeEach(() => {
    useAuthStore.setState({
      activeRole: 'tenant_admin',
      keys: {
        user: '',
        tenant_admin: 'k-admin',
        auditor: '',
        super_admin: '',
      },
      accessToken: '',
      roleEpoch: 0,
    })
    useForbiddenStore.getState().clear()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => [],
        clone: () => ({ json: async () => [] }),
      }),
    )
  })

  it('renders empty org tree copy', async () => {
    render(
      <MemoryRouter>
        <OrgTreePage />
      </MemoryRouter>,
    )
    expect(screen.getByRole('heading', { name: '组织' })).toBeInTheDocument()
    expect(await screen.findByText(/暂无部门/)).toBeInTheDocument()
  })
})
