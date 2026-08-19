import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { useChatStream } from '@/hooks/useChatStream'

vi.mock('@/hooks/useSSEStream', () => ({
  useSSEStream: () => ({
    start: vi.fn(async () => undefined),
    abort: vi.fn(),
  }),
}))

describe('useChatStream local append (45b dig bubbles)', () => {
  it('appendLocal does not set streaming flag', () => {
    const { result } = renderHook(() => useChatStream('/chat/streaming'))
    expect(result.current.streaming).toBe(false)
    act(() => {
      result.current.appendLocal('assistant', '⏳ 正在抓取热点…', 'streaming')
    })
    expect(result.current.streaming).toBe(false)
    expect(result.current.messages).toHaveLength(1)
    expect(result.current.messages[0].content).toContain('抓取')
  })
})

describe('useChatStream history pagination', () => {
  it('replaceHistory sets messages and hasMore', () => {
    const { result } = renderHook(() => useChatStream('/chat/streaming'))
    act(() => {
      result.current.replaceHistory(
        [
          { id: 'a', role: 'user', content: '1', dbId: 1 },
          { id: 'b', role: 'assistant', content: '2', dbId: 2 },
        ],
        true,
      )
    })
    expect(result.current.messages.map((m) => m.id)).toEqual(['a', 'b'])
    expect(result.current.hasMore).toBe(true)
  })

  it('prependHistory inserts older rows and dedupes by id', () => {
    const { result } = renderHook(() => useChatStream('/chat/streaming'))
    act(() => {
      result.current.replaceHistory(
        [
          { id: 'b', role: 'user', content: '2', dbId: 2 },
          { id: 'c', role: 'assistant', content: '3', dbId: 3 },
        ],
        true,
      )
    })
    act(() => {
      result.current.prependHistory(
        [
          { id: 'a', role: 'user', content: '1', dbId: 1 },
          { id: 'b', role: 'user', content: '2-dup', dbId: 2 },
        ],
        false,
      )
    })
    expect(result.current.messages.map((m) => m.id)).toEqual(['a', 'b', 'c'])
    expect(result.current.messages[0].content).toBe('1')
    expect(result.current.messages[1].content).toBe('2')
    expect(result.current.hasMore).toBe(false)
  })
})
