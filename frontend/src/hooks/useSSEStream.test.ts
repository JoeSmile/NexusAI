import { describe, expect, it, vi } from 'vitest'

import { consumeSSEBuffer, dispatchSSEData } from './sseParse'

describe('SSE parse (30.12 core; full stream suite → 30.26)', () => {
  it('ignores : ping comment lines', () => {
    const onToken = vi.fn()
    const onError = vi.fn()
    const { stopped } = consumeSSEBuffer(': ping\n\ndata: {"token":"hi"}\n\n', {
      onToken,
      onError,
    })
    expect(stopped).toBe(false)
    expect(onToken).toHaveBeenCalledTimes(1)
    expect(onToken).toHaveBeenCalledWith('hi')
    expect(onError).not.toHaveBeenCalled()
  })

  it('handles abort and stops', () => {
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

  it('handles error and [DONE]', () => {
    const onError = vi.fn()
    const onDone = vi.fn()
    expect(dispatchSSEData('{"type":"error","code":"LLM_002","message":"boom"}', { onError })).toBe(
      'done',
    )
    expect(onError).toHaveBeenCalledWith('LLM_002', 'boom')
    expect(dispatchSSEData('[DONE]', { onDone })).toBe('done')
    expect(onDone).toHaveBeenCalledWith({ path: 'long' })
  })

  it('JSON short-path shape via dispatch of response is caller-side', () => {
    // 短路径由 useSSEStream.start 读 application/json；此处保证 token 帧兼容
    const onToken = vi.fn()
    dispatchSSEData('{"token":"a"}', { onToken })
    expect(onToken).toHaveBeenCalledWith('a')
  })
})
