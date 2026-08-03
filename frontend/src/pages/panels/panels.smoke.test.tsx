import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RequestPanel } from '@/components/panels/RequestPanel'
import CapabilitiesPanel from '@/pages/panels/capabilities'
import ChatPanel from '@/pages/panels/chat'
import RagPanel from '@/pages/panels/rag'
import { useAuthStore } from '@/stores/authStore'
import { useForbiddenStore } from '@/stores/forbiddenStore'

function wrap(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

describe('panel smoke (empty / idle)', () => {
  beforeEach(() => {
    useAuthStore.setState({
      activeRole: 'user',
      keys: {
        user: 'k-user',
        tenant_admin: '',
        auditor: '',
        super_admin: '',
      },
      roleEpoch: 0,
    })
    useForbiddenStore.getState().clear()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({
          success: true,
          data: {
            cache: { hit_ratio: 0, hit: 0, miss: 0, enabled: true },
            document_count: 0,
          },
          items: [],
          total: 0,
        }),
        clone: () => ({ json: async () => ({}) }),
      }),
    )
  })

  it('ChatPanel renders idle empty hint', () => {
    wrap(<ChatPanel />)
    expect(screen.getByRole('heading', { name: 'Chat' })).toBeInTheDocument()
    expect(
      screen.getByText(/空态 — 发「你好」多走短路径/),
    ).toBeInTheDocument()
  })

  it('RagPanel renders title and ask controls', () => {
    wrap(<RagPanel />)
    expect(screen.getByRole('heading', { name: 'RAG' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ask' })).toBeInTheDocument()
  })

  it('CapabilitiesPanel renders empty list copy', async () => {
    wrap(<CapabilitiesPanel />)
    expect(screen.getByRole('heading', { name: 'Capabilities' })).toBeInTheDocument()
    expect(await screen.findByText('无可见能力')).toBeInTheDocument()
  })

  it('RequestPanel shows send control before request', () => {
    wrap(
      <RequestPanel
        title="Probe"
        description="smoke"
        endpoint="/health"
        fields={[{ name: 'q', label: 'q', defaultValue: '' }]}
        onSend={async () => ({ ok: true })}
      />,
    )
    expect(screen.getByText('Probe')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^发送$/ })).toBeInTheDocument()
  })
})
