import { renderHook } from '@testing-library/react'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '@/stores/authStore'
import { useSSEStream } from '@/hooks/useSSEStream'

/**
 * 永不 push/close 的 body → reader.read() 永久 pending（服务端假死/静默断网）。
 * 但必须把 AbortSignal 接进流：watchdog/用户 abort 需要让 read 以 AbortError 拒绝，
 * 否则 abort 打不断 pending read，start() 永不返回（真浏览器里 fetch abort 会断流）。
 */
function stalledBody(signal?: AbortSignal): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      signal?.addEventListener('abort', () => {
        controller.error(
          signal.reason ?? new DOMException('This operation was aborted', 'AbortError'),
        )
      })
    },
  })
}

function sseResponse(body: ReadableStream<Uint8Array>): Response {
  return {
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': 'text/event-stream' }),
    body,
  } as unknown as Response
}

/** fetch stub：把 RequestInit.signal 传给 body 流（mock 也要尊重 abort）。 */
function stubFetchWith(bodyFactory: (signal?: AbortSignal) => ReadableStream<Uint8Array>) {
  vi.stubGlobal(
    'fetch',
    vi.fn((_url: string, init?: RequestInit) =>
      Promise.resolve(sseResponse(bodyFactory(init?.signal))),
    ),
  )
}

beforeEach(() => {
  sessionStorage.clear()
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
  vi.unstubAllGlobals()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('useSSEStream idle watchdog (Task 94 S3)', () => {
  it('silent stall beyond idleTimeoutMs → onNetworkError（非 onAbort）', async () => {
    vi.useFakeTimers()
    stubFetchWith((sig) => stalledBody(sig))
    const { result } = renderHook(() => useSSEStream({ idleTimeoutMs: 60 }))
    const onNetworkError = vi.fn()
    const onAbort = vi.fn()
    const onError = vi.fn()
    let settled = false
    const p = result.current
      .start('/x', { method: 'POST' }, { onNetworkError, onAbort, onError })
      .then(() => {
        settled = true
      })
    await vi.advanceTimersByTimeAsync(80)
    await p
    expect(settled).toBe(true)
    // watchdog = 网络错误语义（走断线续传），不是本地止血的 onAbort
    expect(onNetworkError).toHaveBeenCalledTimes(1)
    expect(onNetworkError).toHaveBeenCalledWith(expect.any(Error))
    expect(onAbort).not.toHaveBeenCalled()
    expect(onError).not.toHaveBeenCalled()
  })

  it('bytes reset the idle budget (ping 续命)', async () => {
    vi.useFakeTimers()
    const enc = new TextEncoder()
    let enqueue: ((u: Uint8Array) => void) | undefined
    stubFetchWith((sig) => {
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          sig?.addEventListener('abort', () => {
            controller.error(
              sig.reason ?? new DOMException('This operation was aborted', 'AbortError'),
            )
          })
          enqueue = (u) => controller.enqueue(u)
        },
      })
      return stream
    })
    const { result } = renderHook(() => useSSEStream({ idleTimeoutMs: 60 }))
    const onNetworkError = vi.fn()
    let settled = false
    const p = result.current
      .start('/x', { method: 'POST' }, { onNetworkError })
      .then(() => {
        settled = true
      })
    // 每 30ms 一发 ping：watchdog(60ms) 永不触发
    for (let i = 0; i < 8; i += 1) {
      await vi.advanceTimersByTimeAsync(30)
      enqueue?.(enc.encode(': ping\n\n'))
    }
    expect(onNetworkError).not.toHaveBeenCalled()
    expect(settled).toBe(false)
    result.current.abort() // 主动收尾
    await p
    expect(settled).toBe(true)
    expect(onNetworkError).not.toHaveBeenCalled()
  })

  it('user abort() still goes onAbort, not watchdog path', async () => {
    vi.useFakeTimers()
    stubFetchWith((sig) => stalledBody(sig))
    const { result } = renderHook(() => useSSEStream({ idleTimeoutMs: 60 }))
    const onAbort = vi.fn()
    const onNetworkError = vi.fn()
    let settled = false
    const p = result.current
      .start('/x', { method: 'POST' }, { onAbort, onNetworkError })
      .then(() => {
        settled = true
      })
    await vi.advanceTimersByTimeAsync(10)
    result.current.abort()
    await p
    expect(settled).toBe(true)
    expect(onAbort).toHaveBeenCalledWith('client_abort')
    expect(onNetworkError).not.toHaveBeenCalled()
  })
})
