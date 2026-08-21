import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/api/llm', () => ({
  listAvailableModels: vi.fn(async () => ({ items: [] })),
}))
vi.mock('@/api/contentOps', () => ({
  getOrgProfile: vi.fn(async () => ({ profile: {} })),
  putOrgProfile: vi.fn(),
  listStyles: vi.fn(async () => ({ items: [], default_creator_id: 'default' })),
}))
vi.mock('@/api/rag', () => ({
  ragStatus: vi.fn(async () => null),
}))
vi.mock('@/api/memory', () => ({
  listMyMemories: vi.fn(async () => ({ memories: [], total: 0 })),
  patchMyMemory: vi.fn(),
  deleteMyMemory: vi.fn(),
}))

import { ContextPanel, memoryPatchPayload } from '@/components/agent/ContextPanel'

describe('ContextPanel', () => {
  it('shows empty memory copy when there are no warm rows', async () => {
    render(
      <MemoryRouter>
        <ContextPanel open onClose={() => undefined} />
      </MemoryRouter>,
    )
    expect(await screen.findByText('暂无记忆,多聊聊自动积累')).toBeTruthy()
    expect(screen.getByText('记忆面板')).toBeTruthy()
  })

  it('keeps bookmark JSON fields when patching the visible text', () => {
    const payload = memoryPatchPayload(
      {
        id: '1',
        key: 'bookmark:cid',
        value: JSON.stringify({ text: 'old', session_id: 's1', user_message: 'q' }),
        content: 'bookmark:cid: old',
        type: 'bookmark',
        importance: 0.95,
      },
      'new reply',
    )
    expect(JSON.parse(payload)).toEqual({
      text: 'new reply',
      session_id: 's1',
      user_message: 'q',
    })
  })
})
