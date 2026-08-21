import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const fetchUsageSummary = vi.fn()

vi.mock('@/api/audit', () => ({
  fetchUsageSummary: (...args: unknown[]) => fetchUsageSummary(...args),
}))
vi.mock('@/api/contentOps', () => ({
  listArtifacts: vi.fn(async () => ({
    items: [
      { kind: 'script' },
      { kind: 'hotspot_day' },
      { kind: 'hotspot_run' },
    ],
    count: 3,
  })),
}))

import WorkspaceDashboard from '@/pages/agent/WorkspaceDashboard'

describe('WorkspaceDashboard', () => {
  beforeEach(() => {
    fetchUsageSummary.mockReset()
    fetchUsageSummary.mockResolvedValue({
      period: 'today_utc',
      calls: 2,
      input_tokens: 10,
      output_tokens: 20,
      tokens: 30,
      cost: 0.1,
      daily_limit: 10,
    })
  })

  it('shows coarse stats from audit and artifacts', async () => {
    render(
      <MemoryRouter>
        <WorkspaceDashboard />
      </MemoryRouter>,
    )
    expect(await screen.findByText('工作台')).toBeTruthy()
    expect(await screen.findByText('2')).toBeTruthy()
    expect(screen.getByText('2 / 1')).toBeTruthy()
  })

  it('does not show 0 when usage-summary fails', async () => {
    fetchUsageSummary.mockRejectedValue(new Error('audit down'))
    render(
      <MemoryRouter>
        <WorkspaceDashboard />
      </MemoryRouter>,
    )
    expect(await screen.findByText('audit down')).toBeTruthy()
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(3)
  })
})
