import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import WorkflowListPage from '@/pages/workflows/WorkflowList'
import { useAuthStore } from '@/stores/authStore'
import { useForbiddenStore } from '@/stores/forbiddenStore'

function jsonRes(body: unknown) {
  return {
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => body,
    clone: () => jsonRes(body),
  }
}

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

describe('WorkflowList run with ir.inputs', () => {
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
  })

  it('opens a form and posts start_run with input', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = (init?.method || 'GET').toUpperCase()
      if (url.includes('/api/workflows/') && url.includes('/runs') && method === 'POST') {
        return jsonRes({ id: 'run-1', status: 'pending' })
      }
      if (url.includes('/api/workflows') && method === 'GET') {
        return jsonRes({
          items: [
            {
              id: 'wf-llm',
              name: '内置·LLM 生成',
              status: 'published',
              revision: 1,
              ir: {
                ir_schema: '1',
                inputs: {
                  topic: { name: 'topic', type: 'string', required: true, description: '选题' },
                },
                nodes: [{ node_id: 'gen', capability_id: 'llm.generate' }],
              },
            },
          ],
          limit: 50,
          offset: 0,
        })
      }
      return jsonRes({})
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <MemoryRouter>
        <WorkflowListPage />
      </MemoryRouter>,
    )

    await userEvent.click(await screen.findByRole('button', { name: '运行' }))
    const topic = await screen.findByLabelText(/选题/)
    await userEvent.type(topic, '中外合作办学')
    await userEvent.click(screen.getByRole('button', { name: '开始运行' }))

    const post = fetchMock.mock.calls.find(
      ([u, init]) =>
        String(u).includes('/api/workflows/wf-llm/runs') &&
        String((init as RequestInit | undefined)?.method || '').toUpperCase() === 'POST',
    )
    expect(post).toBeTruthy()
    const body = JSON.parse(String((post?.[1] as RequestInit).body))
    expect(body.input.topic).toBe('中外合作办学')
  })
})
