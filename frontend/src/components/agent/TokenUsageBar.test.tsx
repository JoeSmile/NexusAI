import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/api/audit', () => ({
  fetchUsageSummary: vi.fn(async () => ({
    period: 'today_utc',
    calls: 3,
    input_tokens: 100,
    output_tokens: 50,
    tokens: 150,
    cost: 0.42,
    daily_limit: 10,
  })),
}))

import { TokenUsageBar } from '@/components/agent/TokenUsageBar'

describe('TokenUsageBar', () => {
  it('renders today tokens and cost from audit summary', async () => {
    render(<TokenUsageBar />)
    expect(await screen.findByText(/150 tok/)).toBeTruthy()
    expect(screen.getByText(/0.420/)).toBeTruthy()
  })
})
