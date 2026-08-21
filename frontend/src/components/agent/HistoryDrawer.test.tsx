import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/api/chat', () => ({
  WORKSPACE_CHAT_SESSION: 'workspace-chat',
  fetchChatTimeline: vi.fn(async () => ({
    groups: [],
    empty_hint: '还没有历史对话。发一条消息后，可在这里按天回看。',
  })),
  searchChatHistory: vi.fn(async () => ({ items: [] })),
}))

import { HistoryDrawer } from '@/components/agent/HistoryDrawer'

describe('HistoryDrawer', () => {
  it('shows empty hint when there is no history', async () => {
    render(<HistoryDrawer open onClose={() => undefined} />)
    expect(
      await screen.findByText('还没有历史对话。发一条消息后，可在这里按天回看。'),
    ).toBeTruthy()
  })
})
