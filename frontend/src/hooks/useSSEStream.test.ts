import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '@/stores/authStore'

import { createEventParser, dispatchSSEData } from './sseParse'
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
    const parser = createEventParser({ onToken, onError })
    parser.feed(': ping\n\ndata: {"token":"hi"}\n\n')
    expect(parser.stopped()).toBe(false)
    expect(onToken).toHaveBeenCalledWith('hi')
    expect(onError).not.toHaveBeenCalled()
  })

  it('handles abort and stops before later tokens', () => {
    const onAbort = vi.fn()
    const onToken = vi.fn()
    const parser = createEventParser({ onAbort, onToken })
    parser.feed(
      'data: {"type":"abort","reason":"content_filter"}\n\ndata: {"token":"x"}\n\n',
    )
    expect(parser.stopped()).toBe(true)
    expect(onAbort).toHaveBeenCalledWith('content_filter')
    expect(onToken).not.toHaveBeenCalled()
  })

  it('handles retraction without stopping', () => {
    const onRetraction = vi.fn()
    const onToken = vi.fn()
    const parser = createEventParser({ onRetraction, onToken })
    parser.feed(
      'data: {"type":"retraction","reason":"revise"}\n\ndata: {"token":"ok"}\n\n',
    )
    expect(parser.stopped()).toBe(false)
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

  it('passes finish_reason on typed done frame (Task 72 D7)', () => {
    const onDone = vi.fn()
    expect(
      dispatchSSEData(
        '{"type":"done","finish_reason":"fallback","trace_id":"tr-1"}',
        { onDone },
      ),
    ).toBe('done')
    expect(onDone).toHaveBeenCalledWith(
      expect.objectContaining({ finish_reason: 'fallback', trace_id: 'tr-1', path: 'long' }),
    )
  })

  it('handles tool_call and cancelled events', () => {
    const onToolCall = vi.fn()
    const onCancelled = vi.fn()
    const onStreamAlert = vi.fn()
    dispatchSSEData(
      '{"type":"tool_call","step_id":"s1","capability_id":"hotspot.dig","label":"hotspot.dig"}',
      { onToolCall },
    )
    expect(onToolCall).toHaveBeenCalled()
    expect(
      dispatchSSEData('{"type":"cancelled","reason":"user_request"}', {
        onCancelled,
        onStreamAlert,
      }),
    ).toBe('done')
    expect(onCancelled).toHaveBeenCalledWith('user_request')
    expect(onStreamAlert).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'cancelled' }),
    )
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

  it('handles plan and step execution events', () => {
    const onPlan = vi.fn()
    const onStep = vi.fn()
    const parser = createEventParser({ onPlan, onStep })
    parser.feed(
      'data: {"type":"plan","goal":"demo","steps":[{"id":"s1","capability_id":"cap.a"}]}\n\n',
    )
    parser.feed(
      'data: {"type":"step","id":"s1","capability_id":"cap.a","status":"running"}\n\n',
    )
    expect(onPlan).toHaveBeenCalled()
    expect(onStep).toHaveBeenCalled()
    expect(parser.stopped()).toBe(false)
  })

  it('surfaces task_plan_pending as info alert', () => {
    const onStreamAlert = vi.fn()
    const parser = createEventParser({ onStreamAlert })
    parser.feed(
      'data: {"type":"task_plan_pending","status":"pending","message":"正在规划…"}\n\n',
    )
    expect(onStreamAlert).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: 'info',
        code: 'TASK_PLAN_PENDING',
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

  it('JSON error body (LLM_KEY) calls onError not onDone', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({
          type: 'error',
          code: 'LLM_KEY_001',
          message: 'tenant_llm_key_missing',
        }),
      }),
    )
    const { result } = renderHook(() => useSSEStream())
    const onError = vi.fn()
    const onDone = vi.fn()
    await act(async () => {
      await result.current.start('/chat/streaming', { method: 'POST', body: '{}' }, {
        onError,
        onDone,
      })
    })
    expect(onError).toHaveBeenCalledWith('LLM_KEY_001', 'tenant_llm_key_missing')
    expect(onDone).not.toHaveBeenCalled()
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
