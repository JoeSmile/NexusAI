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

  it('turns command_result into a system bubble (Task 78.4)', async () => {
    startMock.mockImplementation(async (_url, _init, h) => {
      h.onToken?.('可用命令：')
      h.onDone?.({ finish_reason: 'command_result', type: 'command_result', command: 'help' })
    })
    const { result } = renderHook(() => useChatStream('/chat/streaming'))
    await act(async () => {
      await result.current.send('/help')
    })
    const sys = result.current.messages.find((m) => m.role === 'system')
    expect(sys?.content).toContain('可用命令')
    expect(result.current.messages.find((m) => m.role === 'assistant')).toBeUndefined()
  })
})

describe('useChatStream image extra (76b)', () => {
  it('keeps imagePreview on the user bubble and omits it from the JSON body', async () => {
    const { result } = renderHook(() => useChatStream('/chat/streaming'))
    await act(async () => {
      await result.current.send('请看看这张图片', {
        session_id: 'workspace-chat',
        imagePreview: 'blob:preview',
      })
    })
    const user = result.current.messages.find((m) => m.role === 'user')
    expect(user?.imagePreview).toBe('blob:preview')
    expect(startMock).toHaveBeenCalledTimes(1)
    const init = startMock.mock.calls[0][1] as { body: string }
    const payload = JSON.parse(init.body) as Record<string, unknown>
    expect(payload.message).toBe('请看看这张图片')
    expect(payload.session_id).toBe('workspace-chat')
    expect(payload).not.toHaveProperty('imagePreview')
    expect(payload).not.toHaveProperty('attachment_ids')
  })
})

describe('useChatStream streaming isolation (Task 85 F1)', () => {
  it('does not replace committed history objects when tokens arrive', async () => {
    startMock.mockImplementation(async (_url, _init, h) => {
      h.onToken?.('he')
      h.onToken?.('llo')
    })
    const { result } = renderHook(() => useChatStream('/chat/streaming'))
    act(() => {
      result.current.replaceHistory(
        [
          { id: 'h1', role: 'user', content: 'old-q', dbId: 1 },
          { id: 'h2', role: 'assistant', content: 'old-a', dbId: 2, status: 'done' },
        ],
        false,
      )
    })
    const hist0 = result.current.messages[0]
    const hist1 = result.current.messages[1]
    await act(async () => {
      await result.current.send('new')
    })
    expect(result.current.messages[0]).toBe(hist0)
    expect(result.current.messages[1]).toBe(hist1)
    const asst = result.current.messages.find((m) => m.status === 'streaming')
    expect(asst?.content).toBe('hello')
  })
})

describe('useChatStream generation guard (Task 85 F3)', () => {
  it('ignores onDone from an aborted previous stream', async () => {
    let firstDone: ((meta?: Record<string, unknown>) => void) | undefined
    startMock
      .mockImplementationOnce(async (_url, _init, h) => {
        firstDone = h.onDone
      })
      .mockImplementationOnce(async (_url, _init, h) => {
        h.onToken?.('second-turn')
      })
    const { result } = renderHook(() => useChatStream('/chat/streaming'))
    await act(async () => {
      await result.current.send('first')
    })
    await act(async () => {
      await result.current.send('second')
    })
    expect(result.current.streaming).toBe(true)
    act(() => {
      firstDone?.({})
    })
    expect(result.current.streaming).toBe(true)
    const live = result.current.messages.filter((m) => m.role === 'assistant')
    expect(live.some((m) => m.content === 'second-turn')).toBe(true)
    expect(live.some((m) => m.status === 'streaming')).toBe(true)
  })
})
