import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '@/stores/authStore'

import { consumeSSEBuffer, dispatchSSEData } from './sseParse'
import { useSSEStream } from './useSSEStream'

function encodeChunks(parts: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder()
  let i = 0
  return new ReadableStream({
    pull(controller) {
      if (i >= parts.length) {
        controller.close()
        return
      }
      controller.enqueue(enc.encode(parts[i++]))
    },
  })
}

describe('SSE parse frames', () => {
  it('ignores : ping comment lines', () => {
    const onToken = vi.fn()
    const onError = vi.fn()
    const { stopped } = consumeSSEBuffer(': ping\n\ndata: {"token":"hi"}\n\n', {
      onToken,
      onError,
    })
    expect(stopped).toBe(false)
    expect(onToken).toHaveBeenCalledWith('hi')
    expect(onError).not.toHaveBeenCalled()
  })

  it('handles abort and stops before later tokens', () => {
    const onAbort = vi.fn()
    const onToken = vi.fn()
    const { stopped } = consumeSSEBuffer(
      'data: {"type":"abort","reason":"content_filter"}\n\ndata: {"token":"x"}\n\n',
      { onAbort, onToken },
    )
    expect(stopped).toBe(true)
    expect(onAbort).toHaveBeenCalledWith('content_filter')
    expect(onToken).not.toHaveBeenCalled()
  })

  it('handles retraction without stopping', () => {
    const onRetraction = vi.fn()
    const onToken = vi.fn()
    const { stopped } = consumeSSEBuffer(
      'data: {"type":"retraction","reason":"revise"}\n\ndata: {"token":"ok"}\n\n',
      { onRetraction, onToken },
    )
    expect(stopped).toBe(false)
    expect(onRetraction).toHaveBeenCalledWith('revise')
    expect(onToken).toHaveBeenCalledWith('ok')
  })

  it('handles error and [DONE]', () => {
    const onError = vi.fn()
    const onDone = vi.fn()
    expect(
      dispatchSSEData('{"type":"error","code":"LLM_002","message":"boom"}', { onError }),
    ).toBe('done')
    expect(onError).toHaveBeenCalledWith('LLM_002', 'boom')
    expect(dispatchSSEData('[DONE]', { onDone })).toBe('done')
    expect(onDone).toHaveBeenCalledWith({ path: 'long' })
  })

  it('handles type=done with call_chain meta', () => {
    const onDone = vi.fn()
    dispatchSSEData(
      '{"type":"done","call_chain":["a","b"],"capability_id":"a"}',
      { onDone },
    )
    expect(onDone).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'done',
        path: 'long',
        call_chain: ['a', 'b'],
      }),
    )
  })
})

describe('useSSEStream dual format', () => {
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

  it('JSON short path calls onToken + onDone', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({ response: 'short-hi', finish_reason: 'stop' }),
      }),
    )
    const { result } = renderHook(() => useSSEStream())
    const onToken = vi.fn()
    const onDone = vi.fn()
    await act(async () => {
      await result.current.start('/chat/streaming', { method: 'POST', body: '{}' }, {
        onToken,
        onDone,
      })
    })
    expect(onToken).toHaveBeenCalledWith('short-hi')
    expect(onDone).toHaveBeenCalledWith(
      expect.objectContaining({ path: 'short', contentType: 'application/json' }),
    )
  })

  it('SSE long path streams tokens, ignores ping, finishes on done', async () => {
    const body = encodeChunks([
      ': ping\n\n',
      'data: {"token":"hel"}\n\n',
      'data: {"token":"lo"}\n\n',
      'data: {"type":"done","path":"long"}\n\n',
      'data: [DONE]\n\n',
    ])
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'text/event-stream' }),
        body,
      }),
    )
    const { result } = renderHook(() => useSSEStream())
    const onToken = vi.fn()
    const onDone = vi.fn()
    const onError = vi.fn()
    await act(async () => {
      await result.current.start('/chat/streaming', { method: 'POST', body: '{}' }, {
        onToken,
        onDone,
        onError,
      })
    })
    expect(onToken.mock.calls.map((c) => c[0]).join('')).toBe('hello')
    expect(onDone).toHaveBeenCalled()
    expect(onError).not.toHaveBeenCalled()
  })

  it('SSE error frame triggers onError', async () => {
    const body = encodeChunks([
      'data: {"type":"error","code":"AUTH_002","message":"forbidden"}\n\n',
    ])
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'text/event-stream' }),
        body,
      }),
    )
    const { result } = renderHook(() => useSSEStream())
    const onError = vi.fn()
    await act(async () => {
      await result.current.start('/x', { method: 'POST', body: '{}' }, { onError })
    })
    expect(onError).toHaveBeenCalledWith('AUTH_002', 'forbidden')
  })
})
