import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useChatStream } from '@/hooks/useChatStream'

const { startMock } = vi.hoisted(() => ({
  startMock: vi.fn(async () => undefined),
}))

vi.mock('@/hooks/useSSEStream', () => ({
  useSSEStream: () => ({
    start: startMock,
    abort: vi.fn(),
  }),
}))

beforeEach(() => {
  startMock.mockReset()
  startMock.mockImplementation(async () => undefined)
})

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

describe('useChatStream cache_hit from done frame (Task 80.2)', () => {
  it('lands cache_hit and cache_type on the assistant message', async () => {
    startMock.mockImplementation(async (_url, _init, h) => {
      h.onToken?.('cached reply')
      h.onDone?.({
        finish_reason: 'cache_hit',
        cache_hit: true,
        cache_type: 'exact',
      })
    })
    const { result } = renderHook(() => useChatStream('/chat/streaming'))
    await act(async () => {
      await result.current.send('北京天气')
    })
    const asst = result.current.messages.find((m) => m.role === 'assistant')
    expect(asst?.content).toBe('cached reply')
    expect(asst?.cacheHit).toBe(true)
    expect(asst?.cacheType).toBe('exact')
  })

  it('does not set cacheHit on a normal llm_generated done frame', async () => {
    startMock.mockImplementation(async (_url, _init, h) => {
      h.onToken?.('fresh')
      h.onDone?.({ finish_reason: 'llm_generated' })
    })
    const { result } = renderHook(() => useChatStream('/chat/streaming'))
    await act(async () => {
      await result.current.send('你好啊朋友')
    })
    const asst = result.current.messages.find((m) => m.role === 'assistant')
    expect(asst?.cacheHit).toBeFalsy()
    expect(asst?.cacheType).toBeUndefined()
  })

  it('does not badge semantic_cache_hit even if cache_hit is true', async () => {
    startMock.mockImplementation(async (_url, _init, h) => {
      h.onToken?.('near')
      h.onDone?.({ finish_reason: 'semantic_cache_hit', cache_hit: true })
    })
    const { result } = renderHook(() => useChatStream('/chat/streaming'))
    await act(async () => {
      await result.current.send('北京天气如何')
    })
    const asst = result.current.messages.find((m) => m.role === 'assistant')
    expect(asst?.cacheHit).toBeFalsy()
  })
})
