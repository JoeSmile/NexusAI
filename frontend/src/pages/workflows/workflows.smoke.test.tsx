import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import WorkflowListPage from '@/pages/workflows/WorkflowList'
import { useAuthStore } from '@/stores/authStore'
import { useForbiddenStore } from '@/stores/forbiddenStore'

describe('WorkflowList smoke', () => {
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
        json: async () => ({ items: [], limit: 50, offset: 0 }),
        clone: () => ({ json: async () => ({ items: [], limit: 50, offset: 0 }) }),
      }),
    )
  })

  it('renders empty workflows copy', async () => {
    render(
      <MemoryRouter>
        <WorkflowListPage />
      </MemoryRouter>,
    )
    expect(await screen.findByText(/暂无工作流/)).toBeInTheDocument()
  })
})
