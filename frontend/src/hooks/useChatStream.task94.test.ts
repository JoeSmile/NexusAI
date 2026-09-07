/**
 * Task 94 S3 — useChatStream：断线恢复走 poll v2（status 分流 + 终态回填）、
 * cleanup 不发 DELETE（卸载 ≠ 取消）、显式 Stop 仍 DELETE（abort 权威信号）。
 */
import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { SSEHandlers } from '@/hooks/sseParse'
import { useChatStream } from '@/hooks/useChatStream'

const { startMock, abortFetchMock, cancelMock, pollMock } = vi.hoisted(() => ({
  startMock: vi.fn(async () => undefined),
  abortFetchMock: vi.fn(),
  cancelMock: vi.fn(),
  pollMock: vi.fn(),
}))

vi.mock('@/api/chat', () => ({
  cancelChatStream: cancelMock,
}))
vi.mock('@/hooks/streamReconnect', () => ({
  pollRunSnapshot: pollMock,
}))
vi.mock('@/hooks/useSSEStream', () => ({
  useSSEStream: () => ({ start: startMock, abort: abortFetchMock }),
}))

beforeEach(() => {
  startMock.mockReset()
  abortFetchMock.mockReset()
  cancelMock.mockReset()
  pollMock.mockReset()
  startMock.mockImplementation(async () => undefined)
  cancelMock.mockResolvedValue({ ok: true, trace_id: 'tr' })
  pollMock.mockResolvedValue({ result: 'timeout', state: null })
})

describe('Task 94 S3 — cleanup 不发 DELETE（卸载 ≠ 取消）', () => {
  it('卸载中断流只做客户端拆除，绝不 cancelChatStream', () => {
    let handlers: SSEHandlers | null = null
    startMock.mockImplementation((_u, _i, h) => {
      handlers = h
      h.onTraceId?.('tr-1')
      return new Promise(() => undefined) // SSE 挂起
    })
    const { result, unmount } = renderHook(() => useChatStream('/chat/streaming'))
    act(() => {
      void result.current.send('帮我写方案')
    })
    expect(result.current.streaming).toBe(true)
    expect(handlers).not.toBeNull()
    unmount()
    expect(cancelMock).not.toHaveBeenCalled()
  })

  it('显式 Stop（abort）仍发 DELETE——唯一权威取消信号', async () => {
    startMock.mockImplementation(async (_u, _i, h) => {
      h.onTraceId?.('tr-2')
    })
    const { result } = renderHook(() => useChatStream('/chat/streaming'))
    await act(async () => {
      await result.current.send('hi')
    })
    expect(cancelMock).not.toHaveBeenCalled()
    act(() => {
      result.current.abort()
    })
    expect(cancelMock).toHaveBeenCalledWith('tr-2')
    const asst = result.current.messages.find((m) => m.role === 'assistant')
    expect(asst?.status).toBe('aborted')
    expect(result.current.streaming).toBe(false)
  })
})

describe('Task 94 S3 — 断线恢复 poll v2（status 分流 + 终态文本回填）', () => {
  async function streamWithHandlers(): Promise<{
    result: ReturnType<typeof useChatStream>
    handlers: SSEHandlers
  }> {
    let handlers: SSEHandlers | null = null
    startMock.mockImplementation(async (_u, _i, h) => {
      handlers = h
      h.onTraceId?.('tr-3')
    })
    const view = renderHook(() => useChatStream('/chat/streaming'))
    await act(async () => {
      await view.result.current.send('hi')
    })
    expect(handlers).not.toBeNull()
    return { result: view.result, handlers: handlers! }
  }

  it('complete + finalContent → 终态文本回填覆盖本地残缺文本', async () => {
    pollMock.mockResolvedValue({ result: 'complete', state: null, finalContent: 'FULL TEXT' })
    const { result, handlers } = await streamWithHandlers()
    await act(async () => {
      handlers.onNetworkError?.(new Error('idle_timeout'))
    })
    await act(async () => {}) // flush poll .then 链
    const asst = result.current.messages.find((m) => m.role === 'assistant')
    expect(asst?.status).toBe('done')
    expect(asst?.content).toBe('FULL TEXT')
    expect(result.current.streaming).toBe(false)
    expect(result.current.streamAlert?.kind).toBe('info')
    expect(pollMock).toHaveBeenCalledWith(
      expect.objectContaining({
        traceId: 'tr-3',
        assistantClientMessageId: expect.any(String),
      }),
    )
  })

  it('complete 但 DB 无终态文本 → 保留本地部分文本提交 done', async () => {
    pollMock.mockResolvedValue({ result: 'complete', state: null, finalContent: undefined })
    const { result, handlers } = await streamWithHandlers()
    await act(async () => {
      handlers.onToken?.('本地部分文本')
      handlers.onNetworkError?.(new Error('net'))
    })
    await act(async () => {})
    const asst = result.current.messages.find((m) => m.role === 'assistant')
    expect(asst?.status).toBe('done')
    expect(asst?.content).toBe('本地部分文本')
  })

  it('恢复轮询发现已取消 → aborted + cancelled alert', async () => {
    pollMock.mockResolvedValue({ result: 'cancelled', state: null })
    const { result, handlers } = await streamWithHandlers()
    await act(async () => {
      handlers.onNetworkError?.(new Error('net'))
    })
    await act(async () => {})
    const asst = result.current.messages.find((m) => m.role === 'assistant')
    expect(asst?.status).toBe('aborted')
    expect(result.current.streamAlert?.kind).toBe('cancelled')
    expect(result.current.streaming).toBe(false)
  })

  it('恢复轮询发现 failed → error 终态', async () => {
    pollMock.mockResolvedValue({ result: 'failed', state: null })
    const { result, handlers } = await streamWithHandlers()
    await act(async () => {
      handlers.onNetworkError?.(new Error('net'))
    })
    await act(async () => {})
    const asst = result.current.messages.find((m) => m.role === 'assistant')
    expect(asst?.status).toBe('error')
    expect(result.current.streamAlert?.kind).toBe('error')
  })

  it('not_found → 不悬挂，按本地文本提交 done', async () => {
    pollMock.mockResolvedValue({ result: 'not_found', state: null })
    const { result, handlers } = await streamWithHandlers()
    await act(async () => {
      handlers.onToken?.('部分')
      handlers.onNetworkError?.(new Error('net'))
    })
    await act(async () => {})
    const asst = result.current.messages.find((m) => m.role === 'assistant')
    expect(asst?.status).toBe('done')
    expect(result.current.streaming).toBe(false)
  })

  it('断连时无 trace（响应头前断线）→ 不轮询，直接 error 提示', async () => {
    let handlers: SSEHandlers | null = null
    startMock.mockImplementation(async (_u, _i, h) => {
      handlers = h // 不给 onTraceId：模拟响应头前就断
    })
    const { result } = renderHook(() => useChatStream('/chat/streaming'))
    await act(async () => {
      await result.current.send('hi')
    })
    await act(async () => {
      handlers!.onNetworkError?.(new Error('net'))
    })
    await act(async () => {})
    expect(pollMock).not.toHaveBeenCalled()
    expect(result.current.streamAlert?.code).toBe('NET_DISCONNECT')
    expect(result.current.streaming).toBe(false)
  })
})
